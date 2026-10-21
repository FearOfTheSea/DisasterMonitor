"""Durable request scopes: acquisition providers and individual publisher hosts."""

import json
import sqlite3
from urllib.parse import urlsplit

from disaster_monitor.application.ports.collection import (
    COLLECTION_RATE_LIMIT_MINIMUM_SECONDS,
)


def request_scope(row: sqlite3.Row) -> str:
    if row["kind"] != "retrieve":
        return str(row["provider"])
    url = json.loads(row["payload"])["canonical_url"]
    try:
        host = urlsplit(url).hostname
    except ValueError:
        host = None
    return "publisher-host:" + (host or "invalid-url").casefold()


def retained_publisher_refusals(db: sqlite3.Connection) -> dict[str, float]:
    """Recover old header-less 429 backoffs without changing terminal evidence.

    Remove this translation when no retained legacy refusal has an active deadline.
    """
    deadlines: dict[str, float] = {}
    for row in db.execute(
        "SELECT w.*,MAX(a.finished) AS refused_at FROM attempts a "
        "JOIN work w ON w.id=a.work WHERE w.kind='retrieve' "
        "AND a.outcome='article_unavailable' "
        "AND a.detail LIKE 'Publisher HTTP 429;%' GROUP BY w.id"
    ):
        if row["refused_at"] is not None:
            scope = request_scope(row)
            deadlines[scope] = max(
                deadlines.get(scope, 0),
                row["refused_at"] + COLLECTION_RATE_LIMIT_MINIMUM_SECONDS,
            )
    return deadlines


class CollectionRequestSchedule:
    def __init__(
        self, db: sqlite3.Connection, retained_refusals: dict[str, float]
    ) -> None:
        self.cooldowns = dict(db.execute("SELECT provider,until_time FROM cooldowns"))
        for scope, deadline in retained_refusals.items():
            self.cooldowns[scope] = max(self.cooldowns.get(scope, 0), deadline)
        self.publisher_leases: dict[str, float] = {}
        for row in db.execute(
            "SELECT * FROM work WHERE kind='retrieve' AND state='leased'"
        ):
            scope = request_scope(row)
            self.publisher_leases[scope] = max(
                self.publisher_leases.get(scope, 0), row["lease_until"] or 0
            )

    def retry_deadline(self, row: sqlite3.Row) -> float:
        scope = request_scope(row)
        return float(
            max(
                row["due"],
                self.cooldowns.get(scope, 0),
                self.cooldowns.get(row["provider"], 0),
            )
        )

    def ready_at(self, row: sqlite3.Row) -> float:
        return max(
            self.retry_deadline(row),
            self.publisher_leases.get(request_scope(row), 0),
        )
