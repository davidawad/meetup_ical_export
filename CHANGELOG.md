# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **BREAKING: replaced the retired Meetup REST API with OAuth2 + GraphQL.**
  `MEETUP_KEY` is gone. The app now implements Meetup's
  [OAuth2 Server Flow](https://www.meetup.com/graphql/authentication/#p02-server-flow-section)
  (`MEETUP_CLIENT_ID` / `MEETUP_CLIENT_SECRET` / `MEETUP_REDIRECT_URI`) and
  queries `https://api.meetup.com/gql-ext` instead of
  `api.meetup.com/self/groups` and `api.meetup.com/<group>/events`.
- Dependencies bumped off their 2019 pins: Flask 1.0.2 -> 3.1.3,
  requests 2.21.0 -> 2.34.2, icalendar 4.0.3 -> 7.2.2, gunicorn 19.9.0 -> 26.0.0.
- `pytz` and `python-dateutil` dropped as direct dependencies — the app targets
  Python 3.13, so stdlib `zoneinfo` and `datetime.fromisoformat` cover both jobs.
- Python 3.7.2 -> 3.13. `runtime.txt` removed (Heroku deprecated it) in favour
  of `.python-version`.
- The output timezone is now `OUTPUT_TIMEZONE` rather than a constant you edit
  in `app.py`.

### Added

- **A second, credential-free data source.** Meetup's public per-group ICS
  export (`meetup.com/<slug>/events/ical/`) is still live and unauthenticated,
  so `MEETUP_EVENT_SOURCE=ics` + `MEETUP_GROUP_SLUGS=a,b,c` serves a feed with
  no account setup at all. It can't discover memberships and Meetup omits
  `LOCATION` from most events, so `graphql` remains the default — but this
  works today with zero setup. `meetup_ics.py`, verified live end-to-end.
- `meetup_auth.py`: authorization-code exchange, single-use-safe refresh-token
  rotation, and an atomic 0600 token cache at `.token_cache.json`.
- `meetup_api.py`: GraphQL client with cursor pagination and per-group error
  isolation, so one private/deleted group can't take the whole feed down.
- `/oauth2/login` and `/oauth2/callback` routes for the one-time authorization.
- Stable `UID` on every VEVENT, so subscribed calendars update events in place
  instead of duplicating them on each refresh; plus `URL` and `CATEGORIES`.
- A pytest suite (84 tests) covering token refresh, GraphQL query construction,
  pagination, and ical conversion against fixture GraphQL responses. No live
  credentials required — every HTTP call is mocked.
- Repository standards scaffolding via `swe-repo`: LICENSE (MIT), CI, Makefile,
  justfile, pre-commit, renovate, CHANGELOG, PR template, flake.nix.

### Fixed

- Events with an explicit `endTime` now use it; only events with neither
  `endTime` nor `duration` fall back to the 3-hour default.
- The feed cache is now time-based and thread-safe rather than a pair of
  module globals mutated without a lock.
