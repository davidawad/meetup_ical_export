"""Serve every upcoming event from every Meetup group you belong to as one .ics feed.

Subscribe a calendar app to ``/calendar/`` and you never have to open
meetup.com again.

Meetup retired the ``?key=<MEETUP_KEY>`` REST API, so there are now two ways
to get the data, picked with ``MEETUP_EVENT_SOURCE``:

``graphql`` (default)
    OAuth2 + GraphQL — see :mod:`meetup_auth` and :mod:`meetup_api`. Discovers
    your group memberships automatically and returns full structured venue
    addresses. Needs a one-time browser authorization.

``ics``
    Meetup's public per-group ICS export — see :mod:`meetup_ics`. No auth of
    any kind, but it cannot discover memberships (you list the group slugs in
    ``MEETUP_GROUP_SLUGS``) and Meetup omits ``LOCATION`` from most events.

The ical-rendering half of this file is unchanged in spirit — only the field
names it reads moved, because GraphQL's response shape differs from the old
REST JSON.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import threading
from collections.abc import Mapping, Sequence
from typing import Any
from zoneinfo import ZoneInfo

import icalendar
from flask import Flask, make_response, redirect, request, session, url_for

from meetup_api import MeetupAPIError, MeetupGraphQL, fetch_events, fetch_groups
from meetup_auth import MeetupAuth, MeetupAuthError, OAuthConfig, TokenStore
from meetup_ics import MeetupICSError, fetch_events_via_ics, parse_slugs

ICS_FILENAME = "meetup.ics"
OUTPUT_TIMEZONE = os.environ.get("OUTPUT_TIMEZONE", "America/New_York")
PRODID = "-//Meetup Events Export//github.com/davidawad/meetup_ical_export//EN"

# "graphql" (OAuth2, auto-discovers memberships) or "ics" (no auth, needs
# MEETUP_GROUP_SLUGS). See the module docstring for the trade-off.
EVENT_SOURCE = os.environ.get("MEETUP_EVENT_SOURCE", "graphql").strip().lower()
# Explicit group slugs. Required for the "ics" source; with "graphql" it just
# overrides membership auto-discovery.
GROUP_SLUGS = parse_slugs(os.environ.get("MEETUP_GROUP_SLUGS"))

DEBUG = os.environ.get("DEBUG", "").lower() in {"1", "true", "yes", "on"}
# How long a rendered feed is served before we go back to Meetup. Assumes both
# meetups and your life are planned more than a day in advance.
CACHE_TTL = dt.timedelta(hours=int(os.environ.get("CACHE_TTL_HOURS", "24")))
# Events with no end time and no duration get this much room on the calendar.
DEFAULT_EVENT_DURATION = dt.timedelta(hours=3)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)

_auth: MeetupAuth | None = None
_auth_lock = threading.Lock()

# Rendered ics bytes plus the moment they were rendered.
_feed_cache: tuple[bytes, dt.datetime] | None = None
_feed_lock = threading.Lock()

if DEBUG:
    app.logger.warning("DEBUGGING ENABLED")


def get_auth() -> MeetupAuth:
    """Lazily build the shared OAuth handle (env is read on first use, not import)."""
    global _auth
    with _auth_lock:
        if _auth is None:
            _auth = MeetupAuth(OAuthConfig.from_env(), TokenStore())
        return _auth


def get_client() -> MeetupGraphQL:
    return MeetupGraphQL(get_auth().access_token)


# --------------------------------------------------------------------------
# GraphQL event object -> icalendar VEVENT
# --------------------------------------------------------------------------

_ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def parse_iso_duration(value: str | None) -> dt.timedelta | None:
    """Parse Meetup's ``Duration`` scalar, an ISO-8601 duration like ``PT7H30M``."""
    if not value:
        return None
    match = _ISO_DURATION.match(value.strip())
    if not match or not any(match.groupdict().values()):
        return None
    parts = {k: float(v) for k, v in match.groupdict().items() if v is not None}
    return dt.timedelta(
        days=parts.get("days", 0.0),
        hours=parts.get("hours", 0.0),
        minutes=parts.get("minutes", 0.0),
        seconds=parts.get("seconds", 0.0),
    )


def parse_datetime(value: str | None) -> dt.datetime | None:
    """Parse Meetup's ``DateTime`` scalar, e.g. ``2026-08-16T09:00:00-04:00``.

    Meetup emits the group's local time with its UTC offset attached. Anything
    that somehow arrives naive is read as UTC rather than silently drifting.
    """
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def format_address(venues: Sequence[Mapping[str, Any]] | None) -> str:
    """Flatten Meetup's ``venues`` list into one address line.

    ``Event.venues`` is a list: one entry for a physical or online event, two
    for a hybrid one. The first is the one worth putting on the calendar.
    """
    if not venues:
        return ""
    venue = venues[0] or {}
    parts = [
        venue.get("name"),
        venue.get("address"),
        venue.get("city"),
        venue.get("state"),
        venue.get("postalCode"),
    ]
    return ", ".join(part.strip() for part in parts if part and part.strip())


def convert_event_obj_to_ical(e: Mapping[str, Any]) -> icalendar.Event:
    """Turn one GraphQL ``Event`` node into a VEVENT.

    GraphQL fields used, versus what the old REST payload gave us:

    ==================  =========================================
    old REST            GraphQL
    ==================  =========================================
    ``name``            ``title``
    ``time`` (ms epoch) ``dateTime`` (ISO-8601 with offset)
    ``duration`` (ms)   ``duration`` (ISO-8601, e.g. ``PT2H``) /
                        ``endTime`` (ISO-8601) when present
    ``link``            ``eventUrl``
    ``venue`` (object)  ``venues`` (list)
    ==================  =========================================
    """
    start = parse_datetime(e.get("dateTime"))
    if start is None:
        raise ValueError(f"event {e.get('id')!r} has no parseable dateTime")

    end = parse_datetime(e.get("endTime"))
    if end is None:
        end = start + (parse_iso_duration(e.get("duration")) or DEFAULT_EVENT_DURATION)

    link = e.get("eventUrl") or ""
    description = e.get("description") or ""
    if link:
        description = f"{description}\n{link}".strip()

    event = icalendar.Event()
    event.add("summary", e.get("title") or "(untitled Meetup event)")
    event.add("description", description)
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("location", format_address(e.get("venues")))

    # A stable UID is what lets a subscribed calendar update an event in place
    # instead of duplicating it on every refresh. The old REST version had none.
    if e.get("id"):
        event.add("uid", f"{e['id']}@meetup.com")
    if link:
        event.add("url", link)
    group_name = (e.get("group") or {}).get("name")
    if group_name:
        event.add("categories", [group_name])

    return event


def render_calendar(
    vevents: Sequence[icalendar.Event],
    *,
    timezones: Sequence[icalendar.Timezone] = (),
) -> bytes:
    """Wrap VEVENTs in a VCALENDAR.

    ``timezones`` carries the VTIMEZONE components that any ``DTSTART;TZID=...``
    refers to. The GraphQL path doesn't need them (it emits absolute offsets);
    the ICS path does, because Meetup writes TZID-qualified local times.
    """
    cal = icalendar.Calendar()
    cal.add("prodid", PRODID)
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", "Meetup")
    cal.add("X-WR-TIMEZONE", OUTPUT_TIMEZONE)

    for timezone in timezones:
        cal.add_component(timezone)
    for vevent in vevents:
        cal.add_component(vevent)

    return cal.to_ical()


def ical_convert(events: Sequence[Mapping[str, Any]]) -> bytes:
    """Render a list of GraphQL ``Event`` nodes as a VCALENDAR."""
    vevents = []
    for e in events:
        try:
            vevents.append(convert_event_obj_to_ical(e))
        except (ValueError, TypeError) as exc:
            app.logger.warning("skipping unconvertible event %r: %s", e.get("id"), exc)
    return render_calendar(vevents)


# --------------------------------------------------------------------------
# feed assembly
# --------------------------------------------------------------------------


def build_feed_via_graphql() -> bytes:
    """OAuth2 + GraphQL: auto-discovers memberships, full venue addresses."""
    client = get_client()
    groups: Sequence[Mapping[str, Any]]
    if GROUP_SLUGS:
        groups = [{"urlname": slug} for slug in GROUP_SLUGS]
        app.logger.info("using %d configured group slug(s)", len(groups))
    else:
        groups = fetch_groups(client)
        app.logger.info("fetched %d group membership(s)", len(groups))

    events = fetch_events(
        client,
        groups,
        # When debugging, hit one group only so we don't bother Meetup much.
        limit_groups=1 if DEBUG else None,
        on_error=lambda urlname, exc: app.logger.warning(
            "skipping group %s: %s", urlname, exc
        ),
    )
    app.logger.info("fetched %d upcoming event(s)", len(events))
    return ical_convert(events)


def build_feed_via_ics() -> bytes:
    """Meetup's public per-group ICS export: no auth, no membership discovery."""
    if not GROUP_SLUGS:
        raise MeetupICSError(
            "MEETUP_EVENT_SOURCE=ics needs MEETUP_GROUP_SLUGS — the public ICS "
            "export is per group and cannot discover which groups you belong to. "
            "Set MEETUP_GROUP_SLUGS=slug1,slug2 (the bit after meetup.com/ in a "
            "group's URL), or use MEETUP_EVENT_SOURCE=graphql."
        )

    slugs = GROUP_SLUGS[:1] if DEBUG else GROUP_SLUGS
    events, timezones = fetch_events_via_ics(
        slugs,
        on_error=lambda slug, exc: app.logger.warning(
            "skipping group %s: %s", slug, exc
        ),
    )
    app.logger.info(
        "fetched %d upcoming event(s) from %d group(s)", len(events), len(slugs)
    )
    return render_calendar(events, timezones=timezones)


def build_feed() -> bytes:
    if EVENT_SOURCE == "ics":
        return build_feed_via_ics()
    if EVENT_SOURCE != "graphql":
        raise ValueError(
            f"MEETUP_EVENT_SOURCE must be 'graphql' or 'ics', not {EVENT_SOURCE!r}"
        )
    return build_feed_via_graphql()


def fetch_feed(*, now: dt.datetime | None = None) -> bytes:
    """Return the cached ics, re-rendering it when it goes stale."""
    global _feed_cache
    now = now or dt.datetime.now(tz=ZoneInfo(OUTPUT_TIMEZONE))

    with _feed_lock:
        if _feed_cache is not None and (now - _feed_cache[1]) < CACHE_TTL:
            app.logger.info("ICAL_FEED is cached, returning cached copy")
            return _feed_cache[0]

        app.logger.info("ICAL_FEED is either old or nonexistent, fetching new data.")
        feed = build_feed()
        _feed_cache = (feed, now)
        return feed


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


@app.route("/")
def hello():
    """Health check."""
    app.logger.info("Health Check; Hello World.")
    if EVENT_SOURCE == "ics":
        # The public ICS export needs no credentials at all.
        return (
            "Hello World!"
            if GROUP_SLUGS
            else (
                "Hello World! MEETUP_EVENT_SOURCE=ics but MEETUP_GROUP_SLUGS is empty."
            )
        )
    try:
        authorized = get_auth().has_token()
    except MeetupAuthError:
        authorized = False
    return (
        "Hello World!"
        if authorized
        else "Hello World! No Meetup token yet — visit /oauth2/login to authorize."
    )


@app.route("/oauth2/login")
def oauth2_login():
    """Step 1 of the server flow: bounce the browser to Meetup."""
    url, state = get_auth().authorization_url()
    session["oauth_state"] = state
    return redirect(url)


@app.route("/oauth2/callback")
def oauth2_callback():
    """Step 2: Meetup redirects back here with a single-use ``code``."""
    error = request.args.get("error")
    if error:
        return f"Meetup returned an error: {error}", 400

    expected_state = session.pop("oauth_state", None)
    received_state = request.args.get("state")
    if expected_state and received_state != expected_state:
        return "OAuth state mismatch — start again at /oauth2/login.", 400

    code = request.args.get("code")
    if not code:
        return "No authorization code in the callback.", 400

    try:
        get_auth().exchange_code(code)
    except MeetupAuthError as exc:
        return f"Token exchange failed: {exc}", 502

    return (
        "Authorized. The refresh token is cached locally; you should not need "
        f'to do this again. Your feed is at <a href="{url_for("calendar")}">'
        f"{url_for('calendar')}</a>."
    )


@app.route("/calendar/")
def calendar():
    try:
        feed = fetch_feed()
    except MeetupAuthError as exc:
        return f"Not authorized with Meetup yet ({exc}). Visit /oauth2/login.", 401
    except (MeetupAPIError, MeetupICSError) as exc:
        return f"Meetup API error: {exc}", 502

    response = make_response(feed)
    response.headers["Content-Type"] = "text/calendar; charset=utf-8"
    response.headers["Content-Disposition"] = f"attachment; filename={ICS_FILENAME}"
    return response


# for quick local testing
if __name__ == "__main__":
    import sys

    if "--serve" in sys.argv:
        app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=DEBUG)
    else:
        try:
            sys.stdout.write(build_feed().decode("utf-8"))
        except (MeetupAuthError, MeetupAPIError, MeetupICSError) as exc:
            sys.stderr.write(f"{exc}\n")
            raise SystemExit(3) from exc
