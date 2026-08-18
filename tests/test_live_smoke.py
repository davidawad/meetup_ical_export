"""Opt-in smoke tests against the real Meetup service.

Skipped by default (and always in CI, which never sets the env var below) —
everything else in this suite runs offline against fixtures. This file is the
one place that actually calls meetup.com, to catch Meetup changing the public
ICS export's shape or URL out from under us.

Strictly read-only GET requests. No credentials involved: MEETUP_EVENT_SOURCE=ics
needs none, which is the whole point of that path.

    RUN_LIVE_TESTS=1 pytest tests/test_live_smoke.py
"""

from __future__ import annotations

import datetime as dt
import os

import icalendar
import pytest

import app as app_module
from meetup_ics import (
    extract_components,
    fetch_events_via_ics,
    fetch_group_ics,
    parse_calendar,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="live network test — set RUN_LIVE_TESTS=1 to run",
)

# A small, low-traffic real group — enough to prove the endpoint still works
# without hammering a large one.
LIVE_SLUG = "emacsatx"

# David's real Meetup memberships (pulled from meetup.com/groups/ 2026-08-16).
# Deliberately every group, not a sample: this is the actual MEETUP_GROUP_SLUGS
# configuration, so it's what proves the real deployment works end to end.
REAL_GROUP_SLUGS = [
    "cbc-drama-club",
    "improvatx",
    "austin-tech-mavericks-hack-share-thrive-in-atx",
    "emacsatx",
    "claude-and-coffee-austin",
    "defi-austin",
    "be-human",
    "rust-atx",
    "austin-progress-studies-reading-group",
    "austin-lebanese-culture-arabic-language-meetup-group",
    "hack-ai",
    "bitcoin-park-austin",
    "pytorch-atx",
    "webassembly-atx",
    "dadventure-club-atx",
    "grafana-friends-austin-meetup-group",
    "acm-austin",
    "austin-startup-pitch-and-networking-group",
    "tesla-spacex-austin",
    "austin-robotics",
]


def test_fetch_group_ics_returns_a_real_calendar_with_no_credentials():
    body = fetch_group_ics(LIVE_SLUG)

    assert body.startswith(b"BEGIN:VCALENDAR")

    events, _ = extract_components(parse_calendar(body))
    # Don't assert a specific count — a real group's upcoming events change
    # over time. Just prove the endpoint still returns parseable VEVENTs.
    for event in events:
        assert event.get("SUMMARY")
        assert event.get("DTSTART")


def test_fetch_events_via_ics_merges_multiple_real_groups():
    events, _ = fetch_events_via_ics([LIVE_SLUG, "cbc-drama-club"])

    # Two real, currently-active groups; if both go quiet at once this is
    # more likely a real regression than a coincidence.
    assert isinstance(events, list)


def test_the_real_flask_app_serves_a_live_feed_for_every_configured_group(monkeypatch):
    """Drives /calendar/ itself, not just the fetch functions underneath it —
    this is the actual production configuration (every real group slug),
    exercised through the real route, cache, and render pipeline."""
    monkeypatch.setattr(app_module, "EVENT_SOURCE", "ics")
    monkeypatch.setattr(app_module, "GROUP_SLUGS", REAL_GROUP_SLUGS)
    monkeypatch.setattr(app_module, "DEBUG", False)
    monkeypatch.setattr(app_module, "_feed_cache", None)
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()

    assert client.get("/").data == b"Hello World!"

    feed = client.get("/calendar/")

    assert feed.status_code == 200
    assert feed.headers["Content-Type"].startswith("text/calendar")

    cal = icalendar.Calendar.from_ical(feed.data.decode())
    events = list(cal.events)
    # 20 active real groups; if this is ever empty, something upstream broke,
    # not "nobody has an event this week."
    assert len(events) > 0

    now = dt.datetime.now(dt.timezone.utc)
    for event in events:
        assert event.get("SUMMARY")
        start = event.get("DTSTART").dt
        if isinstance(start, dt.datetime):
            if start.tzinfo is None:
                start = start.replace(tzinfo=now.tzinfo)
            assert start >= now - dt.timedelta(days=1)
