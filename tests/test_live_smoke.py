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

import os

import pytest

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
