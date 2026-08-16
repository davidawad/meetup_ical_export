# meetup_ical_export

Finds every Meetup group you belong to, pulls all of their upcoming events, and
serves them as a single `.ics` feed at `/calendar/` — so you can subscribe from
any calendar app and never open meetup.com again.

## What changed (2026)

Meetup retired the old REST API. The `?key=<MEETUP_KEY>` query-param auth and
the `api.meetup.com/self/groups` / `api.meetup.com/<group>/events` endpoints are
gone. Everything now goes through:

- **OAuth2**, via Meetup's [Server
  Flow](https://www.meetup.com/graphql/authentication/#p02-server-flow-section)
  — `https://secure.meetup.com/oauth2/authorize` then
  `https://secure.meetup.com/oauth2/access`.
- **GraphQL**, at the single endpoint `https://api.meetup.com/gql-ext`
  ([guide](https://www.meetup.com/graphql/guide/)).

So `MEETUP_KEY` no longer exists. See setup below.

## Setup

### 1. Register an OAuth consumer (one time, manual)

Go to <https://www.meetup.com/api/oauth/list/> and create a consumer. You need
to fill in:

| Field | What to put |
| --- | --- |
| Consumer name | anything, e.g. `meetup_ical_export` |
| Redirect URI | `http://localhost:5000/oauth2/callback` for local use, or `https://<your-app>.herokuapp.com/oauth2/callback` if you deploy it |

Meetup hands back a **client key** and a **client secret**. The redirect URI you
send at authorization time must *start with* the one you registered here.

### 2. Set the environment variables

```sh
export MEETUP_CLIENT_ID='<your consumer key>'
export MEETUP_CLIENT_SECRET='<your consumer secret>'
export MEETUP_REDIRECT_URI='http://localhost:5000/oauth2/callback'
```

Every variable the app reads is documented in [`.env.example`](.env.example).

### 3. Install

```sh
make install     # uv venv + requirements-dev.txt + pre-commit hooks
```

or, without the dev tooling:

```sh
pip install -r requirements.txt
```

### 4. Authorize once, in a browser

```sh
make serve                       # http://localhost:5000
open http://localhost:5000/oauth2/login
```

That bounces you to Meetup, you approve, and Meetup redirects back to
`/oauth2/callback` with a single-use code. The app trades that code for an
access token plus a refresh token and writes them to `.token_cache.json`
(gitignored, mode 0600).

**This is the only step that needs a human.** From then on the app refreshes
itself: access tokens last an hour, and each refresh mints a new refresh token
that replaces the cached one.

> Meetup's refresh tokens are **single use** — reusing one invalidates the whole
> session. The app therefore serialises refreshes behind a lock and writes the
> replacement atomically. Don't hand-edit or copy `.token_cache.json` around; if
> it does get invalidated, delete it and run `/oauth2/login` again.

### 5. Use it

```sh
make run                         # dump the .ics to stdout
```

or subscribe your calendar to `http://localhost:5000/calendar/`.

| Route | Purpose |
| --- | --- |
| `/` | health check; also tells you whether a token is cached |
| `/oauth2/login` | one-time authorization — redirects to Meetup |
| `/oauth2/callback` | where Meetup redirects back; exchanges the code |
| `/calendar/` | the `.ics` feed (cached for `CACHE_TTL_HOURS`, default 24) |

## Environment variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `MEETUP_CLIENT_ID` | yes | — | OAuth consumer key |
| `MEETUP_CLIENT_SECRET` | yes | — | OAuth consumer secret |
| `MEETUP_REDIRECT_URI` | no | `http://localhost:5000/oauth2/callback` | must match what you registered |
| `MEETUP_TOKEN_CACHE` | no | `.token_cache.json` | where the token pair is persisted |
| `MEETUP_API_URL` | no | `https://api.meetup.com/gql-ext` | GraphQL endpoint override |
| `OUTPUT_TIMEZONE` | no | `America/New_York` | the feed's `X-WR-TIMEZONE` |
| `CACHE_TTL_HOURS` | no | `24` | how long a rendered feed is served before refetching |
| `FLASK_SECRET_KEY` | no | random per process | signs the session cookie holding the OAuth `state` |
| `DEBUG` | no | off | verbose logging, and only queries the first group |

### Not in EST?

Set `OUTPUT_TIMEZONE` to your own [IANA timezone
name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) — e.g.
`export OUTPUT_TIMEZONE=Europe/Berlin`. It no longer needs editing in `app.py`.

Individual event times are not affected by this: Meetup returns each event's
start with its own UTC offset attached and the feed preserves it, so events show
up at the right wall-clock time wherever the group actually is.

## Deployment

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/davidawad/meetup_ical_export)

Set the config vars `MEETUP_CLIENT_ID`, `MEETUP_CLIENT_SECRET` and
`MEETUP_REDIRECT_URI` (pointing at your app's own
`/oauth2/callback`), then hit `/oauth2/login` once on the deployed URL.

One caveat on ephemeral filesystems like Heroku's: `.token_cache.json` does not
survive a dyno restart, so you'd have to re-authorize after each one. Point
`MEETUP_TOKEN_CACHE` at persistent storage, or just run it somewhere with a real
disk.

## Layout

| File | What it is |
| --- | --- |
| `app.py` | Flask routes, GraphQL-event → VEVENT conversion, feed caching |
| `meetup_auth.py` | OAuth2 server flow: authorize URL, code exchange, refresh, token cache |
| `meetup_api.py` | GraphQL client + the two queries that replace the old REST calls |
| `tests/` | pytest suite; every HTTP call is mocked, no live credentials needed |

## Development

```sh
make ci          # lint + typecheck + test + dependency audit
make test
make fmt
```
