"""Canned Meetup GraphQL responses, shaped exactly like the real API.

Field names and value formats are taken from the published schema and from
recorded responses: ``dateTime`` is ISO-8601 with a UTC offset
(``2026-09-21T09:00:00+01:00``) and ``duration`` is an ISO-8601 duration
(``PT7H``).
"""

from __future__ import annotations

from typing import Any


def self_groups_page(
    nodes: list[dict[str, Any]],
    *,
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "data": {
            "self": {
                "id": "1234567",
                "name": "David Awad",
                "memberships": {
                    "totalCount": len(nodes),
                    "pageInfo": {
                        "hasNextPage": has_next_page,
                        "endCursor": end_cursor,
                    },
                    "edges": [{"node": node} for node in nodes],
                },
            }
        }
    }


def group_events_page(
    urlname: str,
    nodes: list[dict[str, Any]],
    *,
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "data": {
            "groupByUrlname": {
                "id": "99",
                "name": urlname,
                "urlname": urlname,
                "timezone": "America/New_York",
                "events": {
                    "totalCount": len(nodes),
                    "pageInfo": {
                        "hasNextPage": has_next_page,
                        "endCursor": end_cursor,
                    },
                    "edges": [{"node": node} for node in nodes],
                },
            }
        }
    }


GROUP_NODE = {
    "id": "18234310",
    "name": "NYC Python",
    "urlname": "nycpython",
    "timezone": "America/New_York",
    "link": "https://www.meetup.com/nycpython/",
}

SECOND_GROUP_NODE = {
    "id": "18234311",
    "name": "Papers We Love",
    "urlname": "papers-we-love",
    "timezone": "America/New_York",
    "link": "https://www.meetup.com/papers-we-love/",
}

# A fully-populated in-person event.
EVENT_NODE = {
    "id": "308123456",
    "title": "Monthly Python Meetup",
    "eventUrl": "https://www.meetup.com/nycpython/events/308123456/",
    "description": "Talks and pizza.",
    "dateTime": "2026-09-21T19:00:00-04:00",
    "endTime": None,
    "duration": "PT2H30M",
    "status": "ACTIVE",
    "group": {
        "id": "18234310",
        "name": "NYC Python",
        "urlname": "nycpython",
        "timezone": "America/New_York",
    },
    "venues": [
        {
            "id": "27069153",
            "name": "Stack Overflow HQ",
            "address": "110 William St",
            "city": "New York",
            "state": "NY",
            "postalCode": "10038",
            "country": "us",
        }
    ],
}

# An online event: explicit endTime, no duration, venue with no street address.
ONLINE_EVENT_NODE = {
    "id": "308123457",
    "title": "Online Lightning Talks",
    "eventUrl": "https://www.meetup.com/papers-we-love/events/308123457/",
    "description": "Five minutes each.",
    "dateTime": "2026-10-01T18:00:00-04:00",
    "endTime": "2026-10-01T20:00:00-04:00",
    "duration": None,
    "status": "ACTIVE",
    "group": {
        "id": "18234311",
        "name": "Papers We Love",
        "urlname": "papers-we-love",
        "timezone": "America/New_York",
    },
    "venues": [
        {
            "id": "26906060",
            "name": "Online event",
            "address": None,
            "city": None,
            "state": None,
            "postalCode": None,
            "country": None,
        }
    ],
}

# The degenerate case: neither endTime nor duration, and no venue at all.
SPARSE_EVENT_NODE = {
    "id": "308123458",
    "title": "TBD",
    "eventUrl": "https://www.meetup.com/nycpython/events/308123458/",
    "description": "",
    "dateTime": "2026-11-05T18:30:00-05:00",
    "endTime": None,
    "duration": None,
    "status": "ACTIVE",
    "group": {"id": "18234310", "name": "NYC Python", "urlname": "nycpython"},
    "venues": [],
}
