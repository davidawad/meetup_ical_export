"""One full pass through the ics (no-auth) flow against a fake Meetup.

Mirrors what test_end_to_end.py covers for the graphql/OAuth path — merging
multiple groups, surviving a dead group, DEBUG-mode group limiting — but
driven through the actual Flask app for MEETUP_EVENT_SOURCE=ics, the mode
that needs zero credentials. The individual meetup_ics functions already have
unit coverage in test_meetup_ics.py; this file is about the wiring between
them and app.py, the same reason test_end_to_end.py exists.
"""

from __future__ import annotations

from pathlib import Path

import icalendar
import pytest
import responses

import app as app_module
from meetup_ics import GROUP_ICS_URL_TEMPLATE

FIXTURE = Path(__file__).parent / "data" / "group_events.ics"
SAMPLE_ICS_A = FIXTURE.read_bytes()
# Same shape, distinct UIDs — a second group with its own events.
SAMPLE_ICS_B = SAMPLE_ICS_A.replace(b"315642", b"515642")


def url_for_slug(slug: str) -> str:
    return GROUP_ICS_URL_TEMPLATE.format(urlname=slug)


@pytest.fixture
def ics_app(monkeypatch):
    monkeypatch.setattr(app_module, "EVENT_SOURCE", "ics")
    monkeypatch.setattr(app_module, "DEBUG", False)
    monkeypatch.setattr(app_module, "_feed_cache", None)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@responses.activate
def test_health_check_explains_a_missing_group_slug_config(ics_app, monkeypatch):
    monkeypatch.setattr(app_module, "GROUP_SLUGS", [])

    assert b"MEETUP_GROUP_SLUGS is empty" in ics_app.get("/").data


@responses.activate
def test_full_feed_merges_and_dedupes_across_groups_with_no_auth(ics_app, monkeypatch):
    monkeypatch.setattr(app_module, "GROUP_SLUGS", ["group-a", "group-b"])
    responses.get(url_for_slug("group-a"), body=SAMPLE_ICS_A, status=200)
    responses.get(url_for_slug("group-b"), body=SAMPLE_ICS_B, status=200)

    assert ics_app.get("/").data == b"Hello World!"
    feed = ics_app.get("/calendar/")

    assert feed.status_code == 200
    assert feed.headers["Content-Type"].startswith("text/calendar")
    # the whole point of this mode: not one request carries a credential
    assert all("Authorization" not in c.request.headers for c in responses.calls)

    cal = icalendar.Calendar.from_ical(feed.data.decode())
    assert {e.uid for e in cal.events} == {
        "event_315642404@meetup.com",
        "event_315642418@meetup.com",
        "event_515642404@meetup.com",
        "event_515642418@meetup.com",
    }
    # both groups ship an identical America/New_York VTIMEZONE; emit it once
    assert [str(t.get("TZID")) for t in cal.walk("VTIMEZONE")] == ["America/New_York"]


@responses.activate
def test_one_dead_group_does_not_sink_the_feed(ics_app, monkeypatch):
    monkeypatch.setattr(app_module, "GROUP_SLUGS", ["dead", "alive"])
    responses.get(url_for_slug("dead"), body="Not Found", status=404)
    responses.get(url_for_slug("alive"), body=SAMPLE_ICS_A, status=200)

    feed = ics_app.get("/calendar/")

    assert feed.status_code == 200
    cal = icalendar.Calendar.from_ical(feed.data.decode())
    assert len(cal.events) == 2


@responses.activate
def test_debug_mode_only_touches_the_first_configured_group(ics_app, monkeypatch):
    monkeypatch.setattr(app_module, "GROUP_SLUGS", ["group-a", "group-b"])
    monkeypatch.setattr(app_module, "DEBUG", True)
    responses.get(url_for_slug("group-a"), body=SAMPLE_ICS_A, status=200)

    feed = ics_app.get("/calendar/")

    assert feed.status_code == 200
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == url_for_slug("group-a")
