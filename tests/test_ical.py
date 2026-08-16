"""ical rendering against fixture GraphQL responses, plus the Flask routes."""

from __future__ import annotations

import datetime as dt

import icalendar
import pytest
from fixtures import EVENT_NODE, ONLINE_EVENT_NODE, SPARSE_EVENT_NODE

import app as app_module
from app import (
    convert_event_obj_to_ical,
    format_address,
    ical_convert,
    parse_datetime,
    parse_iso_duration,
)


@pytest.fixture(autouse=True)
def clear_feed_cache():
    app_module._feed_cache = None
    yield
    app_module._feed_cache = None


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def span(event: icalendar.Event) -> dt.timedelta:
    """How long a rendered VEVENT runs for."""
    start, end = event.start, event.end
    assert isinstance(start, dt.datetime) and isinstance(end, dt.datetime)
    return end - start


# -- scalar parsing --------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PT7H", dt.timedelta(hours=7)),
        ("PT2H30M", dt.timedelta(hours=2, minutes=30)),
        ("PT45M", dt.timedelta(minutes=45)),
        ("P1DT2H", dt.timedelta(days=1, hours=2)),
        ("PT90S", dt.timedelta(seconds=90)),
    ],
)
def test_parse_iso_duration(value, expected):
    assert parse_iso_duration(value) == expected


@pytest.mark.parametrize("value", [None, "", "banana", "P", "7 hours"])
def test_parse_iso_duration_rejects_junk(value):
    assert parse_iso_duration(value) is None


def test_parse_datetime_keeps_the_offset_meetup_sends():
    parsed = parse_datetime("2026-09-21T19:00:00-04:00")
    assert parsed == dt.datetime(
        2026, 9, 21, 19, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4))
    )


def test_parse_datetime_handles_a_trailing_z():
    parsed = parse_datetime("2026-09-21T23:00:00Z")
    assert parsed is not None and parsed.utcoffset() == dt.timedelta(0)


def test_parse_datetime_treats_a_naive_timestamp_as_utc():
    parsed = parse_datetime("2026-09-21T23:00:00")
    assert parsed is not None and parsed.utcoffset() == dt.timedelta(0)


@pytest.mark.parametrize("value", [None, "", "not-a-date"])
def test_parse_datetime_rejects_junk(value):
    assert parse_datetime(value) is None


# -- venues ----------------------------------------------------------------


def test_format_address_joins_the_first_venue():
    assert format_address(EVENT_NODE["venues"]) == (
        "Stack Overflow HQ, 110 William St, New York, NY, 10038"
    )


def test_format_address_drops_null_parts_of_an_online_venue():
    assert format_address(ONLINE_EVENT_NODE["venues"]) == "Online event"


@pytest.mark.parametrize("venues", [None, [], [{}]])
def test_format_address_survives_a_venueless_event(venues):
    assert format_address(venues) == ""


def test_format_address_uses_the_first_venue_of_a_hybrid_event():
    hybrid = [{"name": "In person", "city": "NYC"}, {"name": "Online event"}]
    assert format_address(hybrid) == "In person, NYC"


# -- event conversion ------------------------------------------------------


def test_convert_event_maps_every_graphql_field():
    event = convert_event_obj_to_ical(EVENT_NODE)

    assert str(event.get("SUMMARY")) == "Monthly Python Meetup"
    assert "Talks and pizza." in str(event.description)
    assert EVENT_NODE["eventUrl"] in str(event.description)
    assert str(event.get("LOCATION")).startswith("Stack Overflow HQ")
    assert event.uid == "308123456@meetup.com"


def test_convert_event_derives_dtend_from_the_duration_scalar():
    event = convert_event_obj_to_ical(EVENT_NODE)
    assert span(event) == dt.timedelta(hours=2, minutes=30)


def test_convert_event_prefers_an_explicit_endtime_over_duration():
    event = convert_event_obj_to_ical(ONLINE_EVENT_NODE)
    assert span(event) == dt.timedelta(hours=2)


def test_convert_event_falls_back_to_three_hours():
    event = convert_event_obj_to_ical(SPARSE_EVENT_NODE)
    assert span(event) == dt.timedelta(hours=3)


def test_convert_event_keeps_the_offset_so_the_time_is_not_shifted():
    event = convert_event_obj_to_ical(EVENT_NODE)
    assert event.start.isoformat() == "2026-09-21T19:00:00-04:00"


def test_convert_event_categorises_by_group_name():
    event = convert_event_obj_to_ical(EVENT_NODE)
    assert "NYC Python" in event.categories


def test_convert_event_without_a_dateTime_is_rejected():
    with pytest.raises(ValueError):
        convert_event_obj_to_ical({**EVENT_NODE, "dateTime": None})


def test_convert_event_titles_an_untitled_event():
    event = convert_event_obj_to_ical({**EVENT_NODE, "title": None})
    assert "untitled" in str(event.get("SUMMARY"))


# -- calendar rendering ----------------------------------------------------


def test_ical_convert_produces_a_parseable_calendar():
    ics = ical_convert([EVENT_NODE, ONLINE_EVENT_NODE, SPARSE_EVENT_NODE])

    cal = icalendar.Calendar.from_ical(ics.decode())
    events = list(cal.events)

    assert ics.startswith(b"BEGIN:VCALENDAR")
    assert len(events) == 3
    assert {e.uid for e in events} == {
        "308123456@meetup.com",
        "308123457@meetup.com",
        "308123458@meetup.com",
    }
    assert cal.get("X-WR-TIMEZONE") is not None


def test_ical_convert_skips_a_broken_event_rather_than_dropping_the_feed():
    ics = ical_convert([EVENT_NODE, {"id": "bad", "dateTime": None}])
    cal = icalendar.Calendar.from_ical(ics.decode())
    assert len(list(cal.walk("VEVENT"))) == 1


def test_ical_convert_of_nothing_is_still_a_valid_calendar():
    cal = icalendar.Calendar.from_ical(ical_convert([]).decode())
    assert list(cal.walk("VEVENT")) == []


# -- routes ----------------------------------------------------------------


def test_health_check_answers_without_credentials(client, monkeypatch):
    monkeypatch.delenv("MEETUP_CLIENT_ID", raising=False)
    monkeypatch.setattr(app_module, "_auth", None)
    response = client.get("/")
    assert response.status_code == 200
    assert b"Hello World!" in response.data


def test_calendar_route_serves_text_calendar(client, monkeypatch):
    monkeypatch.setattr(app_module, "build_feed", lambda: ical_convert([EVENT_NODE]))

    response = client.get("/calendar/")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/calendar")
    assert "meetup.ics" in response.headers["Content-Disposition"]
    assert response.data.startswith(b"BEGIN:VCALENDAR")


def test_calendar_route_serves_the_cache_on_the_second_hit(client, monkeypatch):
    calls = []

    def counting_build():
        calls.append(1)
        return ical_convert([EVENT_NODE])

    monkeypatch.setattr(app_module, "build_feed", counting_build)

    client.get("/calendar/")
    client.get("/calendar/")

    assert len(calls) == 1


def test_calendar_route_rerenders_once_the_cache_expires(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app_module, "build_feed", lambda: (calls.append(1), b"BEGIN:VCALENDAR")[1]
    )
    now = dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.timezone.utc)

    app_module.fetch_feed(now=now)
    app_module.fetch_feed(now=now + dt.timedelta(hours=1))
    app_module.fetch_feed(now=now + dt.timedelta(hours=25))

    assert len(calls) == 2


def test_calendar_route_says_how_to_authorize_when_there_is_no_token(
    client, monkeypatch
):
    def unauthorized():
        raise app_module.MeetupAuthError("no cached Meetup token")

    monkeypatch.setattr(app_module, "build_feed", unauthorized)

    response = client.get("/calendar/")

    assert response.status_code == 401
    assert b"/oauth2/login" in response.data


def test_calendar_route_reports_an_upstream_api_failure(client, monkeypatch):
    def broken():
        raise app_module.MeetupAPIError("rate limited")

    monkeypatch.setattr(app_module, "build_feed", broken)
    assert client.get("/calendar/").status_code == 502


def test_oauth_login_redirects_to_meetup(client, monkeypatch):
    monkeypatch.setenv("MEETUP_CLIENT_ID", "cid")
    monkeypatch.setenv("MEETUP_CLIENT_SECRET", "secret")
    monkeypatch.setattr(app_module, "_auth", None)

    response = client.get("/oauth2/login")

    assert response.status_code == 302
    assert response.headers["Location"].startswith(
        "https://secure.meetup.com/oauth2/authorize?"
    )


def test_oauth_callback_rejects_a_mismatched_state(client, monkeypatch):
    monkeypatch.setenv("MEETUP_CLIENT_ID", "cid")
    monkeypatch.setenv("MEETUP_CLIENT_SECRET", "secret")
    monkeypatch.setattr(app_module, "_auth", None)

    client.get("/oauth2/login")
    response = client.get("/oauth2/callback?code=abc&state=forged")

    assert response.status_code == 400
    assert b"state mismatch" in response.data


def test_oauth_callback_surfaces_a_denial(client):
    response = client.get("/oauth2/callback?error=access_denied")
    assert response.status_code == 400
    assert b"access_denied" in response.data


def test_oauth_callback_without_a_code_is_a_bad_request(client):
    assert client.get("/oauth2/callback").status_code == 400


def test_oauth_callback_exchanges_the_code_and_caches_it(client, monkeypatch, tmp_path):
    from meetup_auth import MeetupAuth, OAuthConfig, TokenStore

    store = TokenStore(tmp_path / ".token_cache.json")
    auth = MeetupAuth(OAuthConfig("cid", "secret", "http://localhost/cb"), store)
    exchanged = []
    monkeypatch.setattr(auth, "exchange_code", lambda code: exchanged.append(code))
    monkeypatch.setattr(app_module, "_auth", auth)

    with client.session_transaction() as flask_session:
        flask_session["oauth_state"] = "st4te"
    response = client.get("/oauth2/callback?code=one-shot&state=st4te")

    assert response.status_code == 200
    assert exchanged == ["one-shot"]
