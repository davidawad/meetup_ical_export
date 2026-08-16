"""OAuth2 server-flow tests. No live Meetup credentials involved — every HTTP
call is intercepted by `responses`."""

from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from meetup_auth import (
    AUTHORIZE_URL,
    TOKEN_URL,
    MeetupAuth,
    MeetupAuthError,
    OAuthConfig,
    Token,
    TokenStore,
)

CONFIG = OAuthConfig(
    client_id="test-client-id",
    client_secret="test-client-secret",
    redirect_uri="http://localhost:5000/oauth2/callback",
)


def sent_form(index: int = 0) -> dict[str, list[str]]:
    """The form-encoded body of a recorded request, as {name: [value]}."""
    body = responses.calls[index].request.body
    if isinstance(body, bytes):
        body = body.decode()
    assert isinstance(body, str)
    return parse_qs(body)


def token_payload(access="access-1", refresh="refresh-1", expires_in=3600):
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": expires_in,
        "refresh_token": refresh,
    }


@pytest.fixture
def store(tmp_path):
    return TokenStore(tmp_path / ".token_cache.json")


@pytest.fixture
def auth(store):
    return MeetupAuth(CONFIG, store)


# -- config ---------------------------------------------------------------


def test_config_from_env_reads_all_three_values():
    config = OAuthConfig.from_env(
        {
            "MEETUP_CLIENT_ID": "cid",
            "MEETUP_CLIENT_SECRET": "secret",
            "MEETUP_REDIRECT_URI": "https://example.com/cb",
        }
    )
    assert (config.client_id, config.client_secret, config.redirect_uri) == (
        "cid",
        "secret",
        "https://example.com/cb",
    )


def test_config_from_env_names_the_missing_variables():
    with pytest.raises(MeetupAuthError) as excinfo:
        OAuthConfig.from_env({"MEETUP_CLIENT_ID": "cid"})
    assert "MEETUP_CLIENT_SECRET" in str(excinfo.value)


# -- step 1: authorization url --------------------------------------------


def test_authorization_url_matches_the_documented_shape(auth):
    url, state = auth.authorization_url()
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_URL
    assert params["client_id"] == ["test-client-id"]
    assert params["response_type"] == ["code"]
    assert params["redirect_uri"] == ["http://localhost:5000/oauth2/callback"]
    assert params["state"] == [state]


def test_authorization_url_state_is_unguessable_and_fresh(auth):
    _, first = auth.authorization_url()
    _, second = auth.authorization_url()
    assert first != second
    assert len(first) >= 16


# -- step 2: authorization-code exchange -----------------------------------


@responses.activate
def test_exchange_code_posts_documented_form_params_and_caches(auth, store):
    responses.post(TOKEN_URL, json=token_payload(), status=200)

    token = auth.exchange_code("one-shot-code")

    sent = sent_form()
    assert sent["grant_type"] == ["authorization_code"]
    assert sent["code"] == ["one-shot-code"]
    assert sent["client_id"] == ["test-client-id"]
    assert sent["client_secret"] == ["test-client-secret"]
    assert sent["redirect_uri"] == ["http://localhost:5000/oauth2/callback"]

    assert token.access_token == "access-1"
    assert store.load().refresh_token == "refresh-1"


@responses.activate
def test_exchange_code_surfaces_meetup_errors(auth):
    responses.post(
        TOKEN_URL,
        json={"error": "invalid_grant", "error_description": "code already used"},
        status=400,
    )
    with pytest.raises(MeetupAuthError, match="code already used"):
        auth.exchange_code("stale-code")


@responses.activate
def test_error_body_with_http_200_is_still_an_error(auth):
    responses.post(TOKEN_URL, json={"error": "invalid_request"}, status=200)
    with pytest.raises(MeetupAuthError, match="invalid_request"):
        auth.exchange_code("code")


# -- step 3: refresh -------------------------------------------------------


@responses.activate
def test_refresh_posts_grant_type_refresh_token(auth, store):
    responses.post(TOKEN_URL, json=token_payload("access-2", "refresh-2"), status=200)

    token = auth.refresh("refresh-1")

    sent = sent_form()
    assert sent["grant_type"] == ["refresh_token"]
    assert sent["refresh_token"] == ["refresh-1"]
    assert "code" not in sent
    assert token.access_token == "access-2"


@responses.activate
def test_refresh_persists_the_rotated_refresh_token(auth, store):
    """Meetup refresh tokens are single use: reusing one invalidates the session,
    so the replacement must hit disk as part of the refresh itself."""
    store.save(Token("old", "refresh-1", expires_at=time.time() - 1))
    responses.post(TOKEN_URL, json=token_payload("access-2", "refresh-2"), status=200)

    auth.access_token()

    assert store.load().refresh_token == "refresh-2"


@responses.activate
def test_access_token_refreshes_only_when_near_expiry(auth, store):
    store.save(Token("still-good", "refresh-1", expires_at=time.time() + 3600))
    assert auth.access_token() == "still-good"
    assert len(responses.calls) == 0


@responses.activate
def test_access_token_refreshes_inside_the_expiry_skew(auth, store):
    # 60s of life left, but the skew is 120s — it must refresh preemptively.
    store.save(Token("about-to-die", "refresh-1", expires_at=time.time() + 60))
    responses.post(TOKEN_URL, json=token_payload("access-2", "refresh-2"), status=200)

    assert auth.access_token() == "access-2"


@responses.activate
def test_access_token_reuses_the_in_memory_token_across_calls(auth, store):
    store.save(Token("expired", "refresh-1", expires_at=time.time() - 1))
    responses.post(TOKEN_URL, json=token_payload("access-2", "refresh-2"), status=200)

    assert auth.access_token() == "access-2"
    assert auth.access_token() == "access-2"
    assert len(responses.calls) == 1  # exactly one refresh, not one per call


def test_access_token_without_a_cache_explains_how_to_authorize(auth):
    with pytest.raises(MeetupAuthError, match="/oauth2/login"):
        auth.access_token()


@responses.activate
def test_refresh_response_missing_a_refresh_token_keeps_the_old_one(auth, store):
    store.save(Token("expired", "refresh-1", expires_at=time.time() - 1))
    responses.post(
        TOKEN_URL,
        json={"access_token": "access-2", "token_type": "bearer", "expires_in": 3600},
        status=200,
    )

    auth.access_token()

    assert store.load().refresh_token == "refresh-1"


# -- Token / TokenStore ----------------------------------------------------


def test_token_from_response_sets_absolute_expiry():
    token = Token.from_response(token_payload(expires_in=3600), now=1000.0)
    assert token.expires_at == 4600.0
    assert not token.is_expired(now=1000.0)
    assert token.is_expired(now=4590.0)  # inside the 120s skew


def test_token_from_response_defaults_expiry_when_absent():
    token = Token.from_response({"access_token": "a", "refresh_token": "r"}, now=0.0)
    assert token.expires_at == 3600.0


def test_token_from_response_rejects_a_body_with_no_access_token():
    with pytest.raises(MeetupAuthError):
        Token.from_response({"refresh_token": "r"})


def test_token_store_roundtrips_and_is_not_world_readable(store):
    token = Token("a", "r", expires_at=123.0)
    store.save(token)
    assert store.load() == token
    assert (store.path.stat().st_mode & 0o077) == 0


def test_token_store_returns_none_when_nothing_cached(store):
    assert store.load() is None


def test_token_store_rejects_a_corrupt_cache(store):
    store.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(MeetupAuthError, match="corrupt"):
        store.load()


def test_token_store_leaves_no_temp_files_behind(store):
    store.save(Token("a", "r", expires_at=1.0))
    assert [p.name for p in store.path.parent.iterdir()] == [store.path.name]


def test_token_store_never_writes_a_partial_file(store, monkeypatch):
    """A failed write must not clobber a good cache — that would strand the
    single-use refresh token."""
    good = Token("a", "refresh-1", expires_at=1.0)
    store.save(good)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        store.save(Token("b", "refresh-2", expires_at=2.0))

    assert json.loads(store.path.read_text())["refresh_token"] == "refresh-1"
