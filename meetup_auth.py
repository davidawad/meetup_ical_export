"""Meetup OAuth2 "Server Flow".

Reference: https://www.meetup.com/graphql/authentication/#p02-server-flow-section

Meetup retired the old ``?key=<MEETUP_KEY>`` REST API. Every call now goes to
the GraphQL endpoint behind an OAuth2 bearer token.

This module implements the *server flow* for the single-user case: the owner of
this deployment authorizes their own Meetup account once in a browser, the
resulting refresh token is cached on disk, and every subsequent run mints a
fresh access token from that cache with no human in the loop.

Two things about Meetup's implementation drive the design here:

1. Access tokens live for one hour (``expires_in: 3600``).
2. **Refresh tokens are single use.** Meetup's docs: "A refresh token is
   designed for single use only. For security reasons, using a refresh token
   multiple times will result in the session being invalidated." So a refresh
   must persist the *new* refresh token before anything else can attempt one,
   and two threads must never refresh concurrently — hence the lock in
   :class:`MeetupAuth` and the atomic write in :class:`TokenStore`.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://secure.meetup.com/oauth2/authorize"
TOKEN_URL = "https://secure.meetup.com/oauth2/access"

DEFAULT_TOKEN_CACHE = ".token_cache.json"
DEFAULT_REDIRECT_URI = "http://localhost:5000/oauth2/callback"

# Refresh this far ahead of the real expiry so a request never dies in flight on
# a token that lapsed between the check and the call.
EXPIRY_SKEW_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 30


class MeetupAuthError(RuntimeError):
    """Meetup refused an authorization/refresh, or no token is cached yet."""


@dataclass(frozen=True)
class OAuthConfig:
    """The three values Meetup's OAuth consumer registration hands you."""

    client_id: str
    client_secret: str
    redirect_uri: str = DEFAULT_REDIRECT_URI

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OAuthConfig:
        env = os.environ if env is None else env
        missing = [
            name
            for name in ("MEETUP_CLIENT_ID", "MEETUP_CLIENT_SECRET")
            if not env.get(name)
        ]
        if missing:
            raise MeetupAuthError(
                "missing required environment variable(s): "
                + ", ".join(missing)
                + " — register an OAuth consumer at "
                "https://www.meetup.com/api/oauth/list/ and export its key/secret"
            )
        return cls(
            client_id=env["MEETUP_CLIENT_ID"],
            client_secret=env["MEETUP_CLIENT_SECRET"],
            redirect_uri=env.get("MEETUP_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
        )


@dataclass(frozen=True)
class Token:
    """An access token plus the refresh token that will replace it."""

    access_token: str
    refresh_token: str
    expires_at: float
    token_type: str = "bearer"

    @classmethod
    def from_response(
        cls,
        payload: Mapping[str, Any],
        *,
        now: float | None = None,
        previous_refresh_token: str | None = None,
    ) -> Token:
        """Build a token from Meetup's JSON token response.

        Shape per the docs::

            {"access_token": "...", "token_type": "bearer",
             "expires_in": 3600, "refresh_token": "..."}
        """
        now = time.time() if now is None else now
        access_token = payload.get("access_token")
        if not access_token:
            raise MeetupAuthError(f"token response had no access_token: {payload!r}")

        # Meetup always returns a fresh refresh_token, but be defensive: if one
        # is ever omitted, carrying the old one forward beats losing the session.
        refresh_token = payload.get("refresh_token") or previous_refresh_token
        if not refresh_token:
            raise MeetupAuthError(f"token response had no refresh_token: {payload!r}")

        try:
            expires_in = float(payload.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600.0

        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=now + expires_in,
            token_type=payload.get("token_type", "bearer"),
        )

    def is_expired(
        self, *, now: float | None = None, skew: float = EXPIRY_SKEW_SECONDS
    ) -> bool:
        now = time.time() if now is None else now
        return now >= (self.expires_at - skew)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Token:
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=float(data["expires_at"]),
            token_type=data.get("token_type", "bearer"),
        )


class TokenStore:
    """Persists a :class:`Token` to a gitignored JSON file, mode 0600."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(
            path or os.environ.get("MEETUP_TOKEN_CACHE") or DEFAULT_TOKEN_CACHE
        )

    def load(self) -> Token | None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            return Token.from_dict(json.loads(raw))
        except (ValueError, KeyError, TypeError) as exc:
            raise MeetupAuthError(f"token cache {self.path} is corrupt: {exc}") from exc

    def save(self, token: Token) -> None:
        """Write atomically — a half-written cache loses the single-use refresh token."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(token.to_dict(), indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class MeetupAuth:
    """Drives the server flow and hands out a currently-valid access token."""

    def __init__(
        self,
        config: OAuthConfig,
        store: TokenStore | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.store = store or TokenStore()
        self.session = session or requests.Session()
        self._lock = threading.Lock()
        self._token: Token | None = None

    # -- step 1: send the member to Meetup --------------------------------
    def authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """Return ``(url, state)`` to redirect the browser to.

        Per the docs the authorization request takes ``client_id``,
        ``response_type=code`` and ``redirect_uri``; ``state`` is an optional
        opaque round-tripped string, used here for CSRF protection.
        """
        state = state or secrets.token_urlsafe(24)
        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "redirect_uri": self.config.redirect_uri,
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}", state

    # -- step 2: swap the one-shot code for a token pair ------------------
    def exchange_code(self, code: str) -> Token:
        token = self._post_token(
            {
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": self.config.redirect_uri,
                "code": code,
            }
        )
        with self._lock:
            self.store.save(token)
            self._token = token
        return token

    # -- step 3: keep it alive forever ------------------------------------
    def refresh(self, refresh_token: str) -> Token:
        token = self._post_token(
            {
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            previous_refresh_token=refresh_token,
        )
        self.store.save(token)
        return token

    def access_token(self, *, now: float | None = None) -> str:
        """A valid bearer token, refreshing (once, under lock) if needed."""
        with self._lock:
            token = self._token or self.store.load()
            if token is None:
                raise MeetupAuthError(
                    "no cached Meetup token — visit /oauth2/login once to "
                    f"authorize, or point MEETUP_TOKEN_CACHE at an existing cache "
                    f"(looked in {self.store.path})"
                )
            if token.is_expired(now=now):
                token = self.refresh(token.refresh_token)
            self._token = token
            return token.access_token

    def has_token(self) -> bool:
        return (self._token or self.store.load()) is not None

    # -- plumbing ----------------------------------------------------------
    def _post_token(
        self,
        data: MutableMapping[str, str],
        *,
        previous_refresh_token: str | None = None,
    ) -> Token:
        response = self.session.post(
            TOKEN_URL,
            data=data,
            headers={"Accept": "application/json"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code != 200 or "error" in payload:
            detail = (
                payload.get("error_description")
                or payload.get("error")
                or response.text
            )
            raise MeetupAuthError(
                f"Meetup token request failed ({response.status_code}): {detail}"
            )

        return Token.from_response(
            payload, previous_refresh_token=previous_refresh_token
        )
