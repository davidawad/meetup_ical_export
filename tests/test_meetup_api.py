"""GraphQL client tests: query construction, pagination, error surfacing."""

from __future__ import annotations

import datetime as dt
import json

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

from meetup_api import (
    GRAPHQL_URL,
    GROUP_EVENTS_QUERY,
    SELF_GROUPS_QUERY,
    MeetupAPIError,
    MeetupGraphQL,
    fetch_events,
    fetch_group_events,
    fetch_groups,
)


@pytest.fixture
def client():
    return MeetupGraphQL(lambda: "access-token-123")


def sent_body(index: int = 0) -> dict:
    """The JSON body of a recorded request."""
    body = responses.calls[index].request.body
    if isinstance(body, bytes):
        body = body.decode()
    assert isinstance(body, str)
    return json.loads(body)


# -- transport -------------------------------------------------------------


@responses.activate
def test_execute_posts_json_with_a_bearer_header(client):
    responses.post(GRAPHQL_URL, json={"data": {"self": {"id": "1"}}}, status=200)

    client.execute("query { self { id } }", {"x": 1})

    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer access-token-123"
    assert request.headers["Content-Type"] == "application/json"
    assert sent_body() == {"query": "query { self { id } }", "variables": {"x": 1}}


@responses.activate
def test_execute_hits_the_gql_ext_endpoint(client):
    responses.post(GRAPHQL_URL, json={"data": {}}, status=200)
    client.execute("query { self { id } }")
    assert responses.calls[0].request.url == "https://api.meetup.com/gql-ext"


@responses.activate
def test_execute_raises_on_a_graphql_errors_array(client):
    responses.post(
        GRAPHQL_URL,
        json={"data": None, "errors": [{"message": "Unauthorized"}]},
        status=200,
    )
    with pytest.raises(MeetupAPIError, match="Unauthorized"):
        client.execute("query { self { id } }")


@responses.activate
def test_execute_raises_on_an_http_error(client):
    responses.post(GRAPHQL_URL, json={"data": None}, status=401)
    with pytest.raises(MeetupAPIError, match="401"):
        client.execute("query { self { id } }")


@responses.activate
def test_execute_raises_on_a_non_json_body(client):
    responses.post(GRAPHQL_URL, body="<html>502 Bad Gateway</html>", status=502)
    with pytest.raises(MeetupAPIError, match="non-JSON"):
        client.execute("query { self { id } }")


@responses.activate
def test_token_provider_is_called_per_request_so_refreshes_take_effect():
    tokens = iter(["first", "second"])
    client = MeetupGraphQL(lambda: next(tokens))
    responses.post(GRAPHQL_URL, json={"data": {}}, status=200)

    client.execute("query { self { id } }")
    client.execute("query { self { id } }")

    assert responses.calls[0].request.headers["Authorization"] == "Bearer first"
    assert responses.calls[1].request.headers["Authorization"] == "Bearer second"


# -- fetch_groups ----------------------------------------------------------


@responses.activate
def test_fetch_groups_returns_group_nodes(client):
    responses.post(GRAPHQL_URL, json=self_groups_page([GROUP_NODE]), status=200)

    groups = fetch_groups(client)

    assert [g["urlname"] for g in groups] == ["nycpython"]
    assert sent_body()["query"] == SELF_GROUPS_QUERY


@responses.activate
def test_fetch_groups_follows_cursor_pages(client):
    responses.post(
        GRAPHQL_URL,
        json=self_groups_page([GROUP_NODE], has_next_page=True, end_cursor="CUR1"),
        status=200,
    )
    responses.post(GRAPHQL_URL, json=self_groups_page([SECOND_GROUP_NODE]), status=200)

    groups = fetch_groups(client)

    assert [g["urlname"] for g in groups] == ["nycpython", "papers-we-love"]
    assert sent_body(0)["variables"]["after"] is None
    assert sent_body(1)["variables"]["after"] == "CUR1"


@responses.activate
def test_fetch_groups_stops_when_hasnextpage_is_true_but_cursor_is_null(client):
    """Defensive: a null endCursor with hasNextPage would otherwise loop forever."""
    responses.post(
        GRAPHQL_URL,
        json=self_groups_page([GROUP_NODE], has_next_page=True, end_cursor=None),
        status=200,
    )
    assert len(fetch_groups(client)) == 1
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_groups_tolerates_a_null_self(client):
    responses.post(GRAPHQL_URL, json={"data": {"self": None}}, status=200)
    assert fetch_groups(client) == []


# -- fetch_group_events ----------------------------------------------------


@responses.activate
def test_fetch_group_events_filters_to_active_events_after_now(client):
    responses.post(
        GRAPHQL_URL, json=group_events_page("nycpython", [EVENT_NODE]), status=200
    )
    after = dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.timezone.utc)

    events = fetch_group_events(client, "nycpython", after=after)

    body = sent_body()
    assert body["query"] == GROUP_EVENTS_QUERY
    assert body["variables"]["urlname"] == "nycpython"
    assert body["variables"]["afterDateTime"] == "2026-08-16T12:00:00+00:00"
    # "UPCOMING" is not an EventStatus in Meetup's schema; ACTIVE + afterDateTime is.
    assert "UPCOMING" not in GROUP_EVENTS_QUERY
    assert "status: [ACTIVE]" in GROUP_EVENTS_QUERY
    assert [e["id"] for e in events] == ["308123456"]


@responses.activate
def test_fetch_group_events_defaults_afterdatetime_to_now(client):
    responses.post(GRAPHQL_URL, json=group_events_page("nycpython", []), status=200)
    fetch_group_events(client, "nycpython")
    sent = sent_body()["variables"]["afterDateTime"]
    assert dt.datetime.fromisoformat(sent).tzinfo is not None


@responses.activate
def test_fetch_group_events_tolerates_a_missing_group(client):
    responses.post(GRAPHQL_URL, json={"data": {"groupByUrlname": None}}, status=200)
    assert fetch_group_events(client, "deleted-group") == []


# -- fetch_events ----------------------------------------------------------


@responses.activate
def test_fetch_events_queries_every_group(client):
    responses.post(
        GRAPHQL_URL, json=group_events_page("nycpython", [EVENT_NODE]), status=200
    )
    responses.post(
        GRAPHQL_URL,
        json=group_events_page("papers-we-love", [ONLINE_EVENT_NODE]),
        status=200,
    )

    events = fetch_events(client, [GROUP_NODE, SECOND_GROUP_NODE])

    assert [e["id"] for e in events] == ["308123456", "308123457"]


@responses.activate
def test_fetch_events_honours_limit_groups_for_debug_runs(client):
    responses.post(
        GRAPHQL_URL, json=group_events_page("nycpython", [EVENT_NODE]), status=200
    )
    fetch_events(client, [GROUP_NODE, SECOND_GROUP_NODE], limit_groups=1)
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_events_skips_a_failing_group_instead_of_losing_the_calendar(client):
    responses.post(
        GRAPHQL_URL,
        json={"errors": [{"message": "group is private"}]},
        status=200,
    )
    responses.post(
        GRAPHQL_URL,
        json=group_events_page("papers-we-love", [ONLINE_EVENT_NODE]),
        status=200,
    )
    seen = []

    events = fetch_events(
        client,
        [GROUP_NODE, SECOND_GROUP_NODE],
        on_error=lambda urlname, exc: seen.append(urlname),
    )

    assert [e["id"] for e in events] == ["308123457"]
    assert seen == ["nycpython"]


@responses.activate
def test_fetch_events_reraises_when_no_error_handler_is_given(client):
    responses.post(GRAPHQL_URL, json={"errors": [{"message": "boom"}]}, status=200)
    with pytest.raises(MeetupAPIError):
        fetch_events(client, [GROUP_NODE])


def test_fetch_events_ignores_groups_with_no_urlname(client):
    assert fetch_events(client, [{"id": "1", "name": "orphan"}]) == []
