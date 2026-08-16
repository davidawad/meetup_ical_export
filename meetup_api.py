"""Meetup GraphQL client — the replacement for the retired REST endpoints.

Everything now goes to a single endpoint, ``https://api.meetup.com/gql-ext``,
as a POST of ``{"query": ..., "variables": {...}}`` with an
``Authorization: Bearer <token>`` header.
(https://www.meetup.com/graphql/guide/)

The two queries here map onto what the old REST calls used to do:

===============================  ==================================================
retired REST call                GraphQL replacement
===============================  ==================================================
``GET /self/groups``             ``self { memberships { edges { node { ... } } } }``
``GET /<urlname>/events``        ``groupByUrlname(urlname:) { events(filter:) }``
===============================  ==================================================

Field names come from the published schema, not from guessing: ``Member`` has
``memberships(after, filter, first, sort): MemberGroupConnection!`` whose edge
``node`` is a ``Group``; ``Group`` has ``events(after, filter, first, sort,
status): GroupEventConnection!`` whose edge ``node`` is an ``Event``.  Note the
schema has no ``UPCOMING`` event status — "upcoming" is expressed as
``filter: {status: [ACTIVE], afterDateTime: <now>}``, sorted ascending.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

import requests

GRAPHQL_URL = os.environ.get("MEETUP_API_URL", "https://api.meetup.com/gql-ext")

HTTP_TIMEOUT_SECONDS = 30
# Meetup's documented budget is 500 points per 60 seconds; modest pages keep the
# per-query point cost down and still finish a normal membership list in one or
# two round trips.
DEFAULT_PAGE_SIZE = 50
# Hard stop so a pathological cursor loop can't spin forever.
MAX_PAGES = 40


class MeetupAPIError(RuntimeError):
    """The GraphQL endpoint returned a transport error or an ``errors`` array."""


SELF_GROUPS_QUERY = """
query SelfGroups($first: Int!, $after: String) {
  self {
    id
    name
    memberships(first: $first, after: $after, filter: {status: [ACTIVE, LEADER]}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          name
          urlname
          timezone
          link
        }
      }
    }
  }
}
"""

GROUP_EVENTS_QUERY = """
query GroupUpcomingEvents(
  $urlname: String!
  $first: Int!
  $after: String
  $afterDateTime: DateTime
) {
  groupByUrlname(urlname: $urlname) {
    id
    name
    urlname
    timezone
    events(
      first: $first
      after: $after
      sort: ASC
      filter: {status: [ACTIVE], afterDateTime: $afterDateTime}
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          id
          title
          eventUrl
          description
          dateTime
          endTime
          duration
          status
          group { id name urlname timezone }
          venues { id name address city state postalCode country }
        }
      }
    }
  }
}
"""


class MeetupGraphQL:
    """Thin authenticated POST-a-query client with cursor pagination."""

    def __init__(
        self,
        token_provider: Callable[[], str],
        *,
        session: requests.Session | None = None,
        url: str = GRAPHQL_URL,
    ) -> None:
        self._token_provider = token_provider
        self.session = session or requests.Session()
        self.url = url

    def execute(
        self, query: str, variables: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self.session.post(
            self.url,
            json={"query": query, "variables": dict(variables or {})},
            headers={
                "Authorization": f"Bearer {self._token_provider()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MeetupAPIError(
                f"Meetup GraphQL returned non-JSON ({response.status_code}): "
                f"{response.text[:200]}"
            ) from exc

        if response.status_code != 200:
            raise MeetupAPIError(
                f"Meetup GraphQL HTTP {response.status_code}: {response.text[:200]}"
            )

        errors = payload.get("errors")
        if errors:
            joined = "; ".join(str(e.get("message", e)) for e in errors)
            raise MeetupAPIError(f"Meetup GraphQL errors: {joined}")

        data = payload.get("data")
        if data is None:
            raise MeetupAPIError(f"Meetup GraphQL response had no data: {payload!r}")
        return data

    def paginate(
        self,
        query: str,
        variables: Mapping[str, Any],
        connection_path: Sequence[str],
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Yield every ``edges[].node`` across cursor pages of one connection."""
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            data = self.execute(
                query, {**variables, "first": page_size, "after": cursor}
            )
            connection = _dig(data, connection_path)
            if not connection:
                return
            for edge in connection.get("edges") or []:
                node = (edge or {}).get("node")
                if node:
                    yield node
            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                return
            cursor = page_info.get("endCursor")
            if not cursor:
                return


def _dig(data: Mapping[str, Any] | None, path: Sequence[str]) -> dict[str, Any] | None:
    """Walk a dotted path through a GraphQL response, tolerating nulls."""
    current: Any = data
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, dict) else None


def fetch_groups(
    client: MeetupGraphQL, *, page_size: int = DEFAULT_PAGE_SIZE
) -> list[dict[str, Any]]:
    """Every group the authenticated member belongs to.

    Replaces the old ``GET api.meetup.com/self/groups``. Each item keeps the
    ``urlname`` key the old REST payload had, so callers read the same field.
    """
    return list(
        client.paginate(
            SELF_GROUPS_QUERY,
            {},
            ("self", "memberships"),
            page_size=page_size,
        )
    )


def fetch_group_events(
    client: MeetupGraphQL,
    urlname: str,
    *,
    after: dt.datetime | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Upcoming events for one group.

    Replaces the old ``GET api.meetup.com/<urlname>/events``.
    """
    after = after or dt.datetime.now(dt.timezone.utc)
    return list(
        client.paginate(
            GROUP_EVENTS_QUERY,
            {"urlname": urlname, "afterDateTime": _iso8601(after)},
            ("groupByUrlname", "events"),
            page_size=page_size,
        )
    )


def fetch_events(
    client: MeetupGraphQL,
    groups: Sequence[Mapping[str, Any]],
    *,
    after: dt.datetime | None = None,
    limit_groups: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    on_error: Callable[[str, Exception], None] | None = None,
) -> list[dict[str, Any]]:
    """Upcoming events across every supplied group.

    One bad group (deleted, gone private, renamed) must not sink the whole
    calendar, so per-group failures are reported to ``on_error`` and skipped.
    """
    events: list[dict[str, Any]] = []
    selected = list(groups)[:limit_groups] if limit_groups else list(groups)
    for group in selected:
        urlname = group.get("urlname")
        if not urlname:
            continue
        try:
            events.extend(
                fetch_group_events(client, urlname, after=after, page_size=page_size)
            )
        except MeetupAPIError as exc:
            if on_error is None:
                raise
            on_error(urlname, exc)
    return events


def _iso8601(moment: dt.datetime) -> str:
    """Meetup's ``DateTime`` scalar is an ISO-8601 timestamp, e.g. 2026-08-16T09:00:00-04:00."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.isoformat(timespec="seconds")
