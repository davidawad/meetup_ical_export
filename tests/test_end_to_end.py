"""One full pass through the whole flow against a fake Meetup.

Nothing here talks to the real service — `responses` stands in for both
`secure.meetup.com` (OAuth2) and `api.meetup.com/gql-ext` (GraphQL). It exists
because the individual units can all pass while the wiring between them is
wrong, and there are no live credentials to catch that with.
"""

from __future__ import annotations

import icalendar
import pytest
import responses
from fixtures import (
    EVENT_NODE,
    GROUP_NODE,
    ONLINE_EVENT_NODE,
    SECOND_GROUP_NODE,
    group_events_page,
    self_groups_page,
)

import app as app_module
from meetup_api import GRAPHQL_URL
from meetup_auth import TOKEN_URL, MeetupAuth, OAuthConfig, TokenStore


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A Flask test client backed by a fresh, unauthorized token cache."""
    store = TokenStore(tmp_path / ".token_cache.json")
    auth = MeetupAuth(
        OAuthConfig("cid", "secret", "http://localhost:5000/oauth2/callback"), store
    )
    monkeypatch.setattr(app_module, "_auth", auth)
    monkeypatch.setattr(app_module, "_feed_cache", None)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client(), store


@responses.activate
def test_authorize_then_serve_a_calendar(wired):
    client, store = wired

    # 1. no token yet: the health check says so and the feed 401s.
    assert b"/oauth2/login" in client.get("/").data
    assert client.get("/calendar/").status_code == 401

    # 2. /oauth2/login bounces to Meetup with the documented params.
    login = client.get("/oauth2/login")
    assert login.status_code == 302
    assert "secure.meetup.com/oauth2/authorize" in login.headers["Location"]
    assert "response_type=code" in login.headers["Location"]

    # 3. Meetup calls us back; we trade the code for a token pair.
    responses.post(
        TOKEN_URL,
        json={
            "access_token": "access-1",
            "token_type": "bearer",
            "expires_in": 3600,
            "refresh_token": "refresh-1",
        },
        status=200,
    )
    with client.session_transaction() as flask_session:
        state = flask_session["oauth_state"]
    callback = client.get(f"/oauth2/callback?code=one-shot&state={state}")
    assert callback.status_code == 200

    cached = store.load()
    assert cached is not None
    assert cached.refresh_token == "refresh-1"

    # 4. the feed now renders from GraphQL, one call per group.
    responses.post(GRAPHQL_URL, json=self_groups_page([GROUP_NODE, SECOND_GROUP_NODE]))
    responses.post(GRAPHQL_URL, json=group_events_page("nycpython", [EVENT_NODE]))
    responses.post(
        GRAPHQL_URL, json=group_events_page("papers-we-love", [ONLINE_EVENT_NODE])
    )

    feed = client.get("/calendar/")

    assert feed.status_code == 200
    assert feed.headers["Content-Type"].startswith("text/calendar")

    cal = icalendar.Calendar.from_ical(feed.data.decode())
    assert {e.uid for e in cal.events} == {
        "308123456@meetup.com",
        "308123457@meetup.com",
    }

    # every GraphQL call carried the freshly-minted bearer token
    graphql_calls = [c for c in responses.calls if c.request.url == GRAPHQL_URL]
    assert len(graphql_calls) == 3
    assert all(
        c.request.headers["Authorization"] == "Bearer access-1" for c in graphql_calls
    )

    # 5. the health check flips over now that a token is cached.
    assert client.get("/").data == b"Hello World!"
