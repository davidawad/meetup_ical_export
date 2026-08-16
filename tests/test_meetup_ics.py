"""Tests for the no-auth public ICS path.

The fixture in ``tests/data/group_events.ics`` is a real response captured from
``https://www.meetup.com/startup-valley/events/ical/`` on 2026-08-16, trimmed to
two events. Nothing here hits the network.
"""

from __future__ import annotations

from pathlib import Path

import icalendar
import pytest
import responses

import app as app_module
from meetup_ics import (
    GROUP_ICS_URL_TEMPLATE,
    MeetupICSError,
    dedupe_by_uid,
    extract_components,
    fetch_events_via_ics,
    fetch_group_ics,
    parse_calendar,
    parse_slugs,
)

FIXTURE = Path(__file__).parent / "data" / "group_events.ics"
SAMPLE_ICS = FIXTURE.read_bytes()


def url_for_slug(slug: str) -> str:
    return GROUP_ICS_URL_TEMPLATE.format(urlname=slug)


# -- slug parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("nycpython,startup-valley", ["nycpython", "startup-valley"]),
        ("nycpython, startup-valley", ["nycpython", "startup-valley"]),
        ("nycpython startup-valley", ["nycpython", "startup-valley"]),
        ("  nycpython  ", ["nycpython"]),
        ("", []),
        (None, []),
    ],
)
def test_parse_slugs(raw, expected):
    assert parse_slugs(raw) == expected


# -- fetching --------------------------------------------------------------


@responses.activate
def test_fetch_group_ics_hits_the_public_per_group_url():
    responses.get(url_for_slug("startup-valley"), body=SAMPLE_ICS, status=200)

    body = fetch_group_ics("startup-valley")

    assert body.startswith(b"BEGIN:VCALENDAR")
    request = responses.calls[0].request
    assert request.url == "https://www.meetup.com/startup-valley/events/ical/"
    # The whole point of this path: no credentials of any kind.
    assert "Authorization" not in request.headers


@responses.activate
def test_fetch_group_ics_raises_on_a_missing_group():
    responses.get(url_for_slug("gone"), body="Not Found", status=404)
    with pytest.raises(MeetupICSError, match="404"):
        fetch_group_ics("gone")


@responses.activate
def test_fetch_group_ics_rejects_an_html_error_page_served_as_200():
    responses.get(url_for_slug("weird"), body="<html>nope</html>", status=200)
    with pytest.raises(MeetupICSError, match="VCALENDAR"):
        fetch_group_ics("weird")


# -- parsing ---------------------------------------------------------------


def test_extract_components_pulls_events_and_their_timezones():
    events, timezones = extract_components(parse_calendar(SAMPLE_ICS))

    assert [str(e.get("UID")) for e in events] == [
        "event_315642404@meetup.com",
        "event_315642418@meetup.com",
    ]
    assert [str(t.get("TZID")) for t in timezones] == ["America/New_York"]


def test_extract_components_keeps_the_fields_a_calendar_needs():
    events, _ = extract_components(parse_calendar(SAMPLE_ICS))
    event = events[0]

    assert str(event.get("SUMMARY")) == "Tech & Business Networking in NYC Manhattan"
    assert str(event.get("URL")).endswith("/events/315642404/")
    assert event.start.isoformat().startswith("2026-08-19T18:00:00")
    assert event.end.isoformat().startswith("2026-08-19T21:00:00")


def test_meetup_omits_location_on_this_export():
    """Documents the actual gap versus GraphQL, so a regression here is visible."""
    events, _ = extract_components(parse_calendar(SAMPLE_ICS))
    assert all(e.get("LOCATION") is None for e in events)


def test_parse_calendar_rejects_junk():
    with pytest.raises(MeetupICSError):
        parse_calendar(b"this is not a calendar")


# -- multi-group assembly --------------------------------------------------


@responses.activate
def test_fetch_events_via_ics_merges_groups_and_dedupes_timezones():
    responses.get(url_for_slug("a"), body=SAMPLE_ICS, status=200)
    responses.get(url_for_slug("b"), body=SAMPLE_ICS.replace(b"315642", b"415642"))

    events, timezones = fetch_events_via_ics(["a", "b"])

    assert len(events) == 4
    # both groups ship an identical America/New_York VTIMEZONE; emit it once
    assert len(timezones) == 1


@responses.activate
def test_fetch_events_via_ics_dedupes_the_same_event_from_two_slugs():
    responses.get(url_for_slug("a"), body=SAMPLE_ICS, status=200)
    responses.get(url_for_slug("b"), body=SAMPLE_ICS, status=200)

    events, _ = fetch_events_via_ics(["a", "b"])

    assert len(events) == 2


@responses.activate
def test_fetch_events_via_ics_skips_a_dead_group():
    responses.get(url_for_slug("dead"), body="Not Found", status=404)
    responses.get(url_for_slug("alive"), body=SAMPLE_ICS, status=200)
    seen = []

    events, _ = fetch_events_via_ics(
        ["dead", "alive"], on_error=lambda slug, exc: seen.append(slug)
    )

    assert len(events) == 2
    assert seen == ["dead"]


@responses.activate
def test_fetch_events_via_ics_reraises_without_a_handler():
    responses.get(url_for_slug("dead"), body="Not Found", status=404)
    with pytest.raises(MeetupICSError):
        fetch_events_via_ics(["dead"])


def test_dedupe_by_uid_keeps_events_that_have_no_uid():
    bare = [icalendar.Event(), icalendar.Event()]
    assert len(list(dedupe_by_uid(bare))) == 2


# -- end to end through the app, with zero credentials ---------------------


@responses.activate
def test_ics_mode_serves_a_feed_with_no_auth_at_all(monkeypatch):
    monkeypatch.setattr(app_module, "EVENT_SOURCE", "ics")
    monkeypatch.setattr(app_module, "GROUP_SLUGS", ["startup-valley"])
    monkeypatch.setattr(app_module, "_feed_cache", None)
    monkeypatch.setattr(app_module, "_auth", None)
    monkeypatch.delenv("MEETUP_CLIENT_ID", raising=False)
    monkeypatch.delenv("MEETUP_CLIENT_SECRET", raising=False)
    responses.get(url_for_slug("startup-valley"), body=SAMPLE_ICS, status=200)

    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()

    assert client.get("/").data == b"Hello World!"
    feed = client.get("/calendar/")

    assert feed.status_code == 200
    assert feed.headers["Content-Type"].startswith("text/calendar")

    cal = icalendar.Calendar.from_ical(feed.data.decode())
    assert {e.uid for e in cal.events} == {
        "event_315642404@meetup.com",
        "event_315642418@meetup.com",
    }
    # the VTIMEZONE must travel with the events — DTSTART;TZID points at it
    assert [str(t.get("TZID")) for t in cal.walk("VTIMEZONE")] == ["America/New_York"]


@responses.activate
def test_ics_mode_without_slugs_explains_why_it_cannot_work(monkeypatch):
    monkeypatch.setattr(app_module, "EVENT_SOURCE", "ics")
    monkeypatch.setattr(app_module, "GROUP_SLUGS", [])
    monkeypatch.setattr(app_module, "_feed_cache", None)

    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().get("/calendar/")

    assert response.status_code == 502
    assert b"MEETUP_GROUP_SLUGS" in response.data


def test_an_unknown_event_source_is_rejected(monkeypatch):
    monkeypatch.setattr(app_module, "EVENT_SOURCE", "carrier-pigeon")
    with pytest.raises(ValueError, match="carrier-pigeon"):
        app_module.build_feed()


@responses.activate
def test_graphql_mode_can_still_use_configured_slugs_instead_of_discovery(monkeypatch):
    """The hybrid: skip the membership query, keep GraphQL's venue data."""
    from fixtures import EVENT_NODE, group_events_page

    from meetup_api import GRAPHQL_URL

    monkeypatch.setattr(app_module, "EVENT_SOURCE", "graphql")
    monkeypatch.setattr(app_module, "GROUP_SLUGS", ["nycpython"])
    monkeypatch.setattr(app_module, "get_client", lambda: _stub_client())
    responses.post(GRAPHQL_URL, json=group_events_page("nycpython", [EVENT_NODE]))

    feed = app_module.build_feed_via_graphql()

    cal = icalendar.Calendar.from_ical(feed.decode())
    assert {e.uid for e in cal.events} == {"308123456@meetup.com"}
    # one call only — no self { memberships } round trip
    assert len(responses.calls) == 1


def _stub_client():
    from meetup_api import MeetupGraphQL

    return MeetupGraphQL(lambda: "stub-token")
