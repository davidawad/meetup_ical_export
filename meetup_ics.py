"""Meetup's public per-group ICS export — the no-auth path.

``https://www.meetup.com/<slug>/events/ical/`` still returns a real VCALENDAR
of a group's upcoming events with no API key, no OAuth, and no token refresh.
Verified 2026-08-16: 200 + VEVENTs with ``UID``, ``DTSTART;TZID=...``,
``DTEND``, ``SUMMARY``, ``DESCRIPTION``, ``URL`` and ``STATUS``, plus the
matching ``VTIMEZONE`` component.

This is a strictly simpler way to get events than GraphQL, and it is what
:mod:`app` uses when ``MEETUP_EVENT_SOURCE=ics``. Two things it cannot do,
which is why :mod:`meetup_api` still exists:

1. **It cannot tell you which groups you belong to.** That is account-specific
   and needs an authenticated ``self { memberships }`` query. With this module
   you supply the slugs yourself via ``MEETUP_GROUP_SLUGS``.
2. **It mostly omits ``LOCATION``.** Meetup's own export only emits a venue
   address for some events, whereas the GraphQL ``venues`` field gives a full
   structured address for every in-person event.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence

import icalendar
import requests

GROUP_ICS_URL_TEMPLATE = "https://www.meetup.com/{urlname}/events/ical/"
HTTP_TIMEOUT_SECONDS = 30


class MeetupICSError(RuntimeError):
    """A group's public ICS export was unreachable or unparsable."""


def fetch_group_ics(urlname: str, *, session: requests.Session | None = None) -> bytes:
    """Download one group's public ICS export."""
    session = session or requests.Session()
    url = GROUP_ICS_URL_TEMPLATE.format(urlname=urlname)
    response = session.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise MeetupICSError(f"{url} returned HTTP {response.status_code}")
    body = response.content
    if not body.lstrip().startswith(b"BEGIN:VCALENDAR"):
        raise MeetupICSError(f"{url} did not return a VCALENDAR")
    return body


def parse_calendar(ics: bytes) -> icalendar.Calendar:
    try:
        return icalendar.Calendar.from_ical(ics.decode("utf-8", errors="replace"))
    except (ValueError, KeyError) as exc:
        raise MeetupICSError(f"could not parse ICS: {exc}") from exc


def extract_components(
    calendar: icalendar.Calendar,
) -> tuple[list[icalendar.Event], list[icalendar.Timezone]]:
    """Pull out the VEVENTs and the VTIMEZONEs their ``TZID``s point at.

    The timezones have to travel with the events: Meetup writes
    ``DTSTART;TZID=America/New_York``, which is meaningless to a calendar app
    without the matching VTIMEZONE in the same VCALENDAR.
    """
    events = [c for c in calendar.walk("VEVENT") if isinstance(c, icalendar.Event)]
    timezones = [
        c for c in calendar.walk("VTIMEZONE") if isinstance(c, icalendar.Timezone)
    ]
    return events, timezones


def fetch_events_via_ics(
    slugs: Sequence[str],
    *,
    session: requests.Session | None = None,
    on_error: Callable[[str, Exception], None] | None = None,
) -> tuple[list[icalendar.Event], list[icalendar.Timezone]]:
    """Every upcoming VEVENT across the given group slugs, plus their VTIMEZONEs.

    As with the GraphQL path, one unreachable group must not sink the feed.
    """
    session = session or requests.Session()
    events: list[icalendar.Event] = []
    timezones: list[icalendar.Timezone] = []

    for slug in slugs:
        try:
            calendar = parse_calendar(fetch_group_ics(slug, session=session))
        except (MeetupICSError, requests.RequestException) as exc:
            if on_error is None:
                raise
            on_error(slug, exc)
            continue
        group_events, group_timezones = extract_components(calendar)
        events.extend(group_events)
        timezones.extend(group_timezones)

    return list(dedupe_by_uid(events)), list(dedupe_timezones(timezones))


def dedupe_by_uid(events: Iterable[icalendar.Event]) -> Iterator[icalendar.Event]:
    """Drop repeats — the same event can surface from two configured slugs."""
    seen: set[str] = set()
    for event in events:
        uid = str(event.get("UID") or "")
        if uid and uid in seen:
            continue
        if uid:
            seen.add(uid)
        yield event


def dedupe_timezones(
    timezones: Iterable[icalendar.Timezone],
) -> Iterator[icalendar.Timezone]:
    """One VTIMEZONE per TZID — every group in the same zone ships its own copy."""
    seen: set[str] = set()
    for timezone in timezones:
        tzid = str(timezone.get("TZID") or "")
        if tzid and tzid in seen:
            continue
        if tzid:
            seen.add(tzid)
        yield timezone


def parse_slugs(raw: str | None) -> list[str]:
    """Read ``MEETUP_GROUP_SLUGS``: comma- or whitespace-separated group slugs."""
    if not raw:
        return []
    return [part for part in raw.replace(",", " ").split() if part]
