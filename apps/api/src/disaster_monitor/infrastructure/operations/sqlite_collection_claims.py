"""Atomic acquisition claims, request budgets and durable priority opportunities."""

import sqlite3
from collections.abc import Generator
from contextlib import closing
from datetime import datetime
from uuid import uuid4

from pydantic import TypeAdapter

from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    CollectionPartition,
    WorkKind,
)
from disaster_monitor.domain.collection_retrieval_priority import (
    preferred_retrieval_priority,
)
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection_citations import (
    ordered_citation_candidates,
)
from disaster_monitor.infrastructure.operations.sqlite_request_schedule import (
    CollectionRequestSchedule,
)

PARTITION = TypeAdapter(CollectionPartition)
LEAD = TypeAdapter(NewsFeedItem)

# Reuse scheduling metadata without decoding saved discovery runs per work row.
ACTIVE_COLLECTION_SCANS = (
    "WITH active_scans AS MATERIALIZED ("
    "SELECT s.id,s.pass_id,p.budget FROM scans s "
    "JOIN passes p ON p.id=s.pass_id WHERE p.active=1 AND p.started>?) "
)
_CANDIDATES = (
    ACTIVE_COLLECTION_SCANS + "SELECT DISTINCT w.*,s.pass_id,s.budget FROM work w "
    "JOIN scan_work sw ON sw.work=w.id "
    "JOIN active_scans s ON s.id=sw.scan "
    "LEFT JOIN cooldowns c ON c.provider=w.provider "
    "LEFT JOIN pass_budget m ON m.pass_id=s.pass_id AND m.provider='all-metadata' "
    "WHERE w.kind=? AND (w.state='pending' OR "
    "(w.state='leased' AND w.lease_until<=?)) "
    "AND w.due<=? AND COALESCE(c.until_time,0)<=? "
    "AND (? IS NULL OR w.provider=?) "
    "AND (w.kind!='search' OR COALESCE(m.remaining,1)>0) "
)

METADATA_BUDGET = "all-metadata"


def initialize_metadata_attempts(db: sqlite3.Connection) -> None:
    """Account for active allocations without inventing closed legacy pass IDs."""
    db.execute("BEGIN IMMEDIATE")
    try:
        columns = {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
        if "pass_id" not in columns:
            db.execute("ALTER TABLE attempts ADD COLUMN pass_id INTEGER")
            # Only the active allocation needs legacy accounting. Closed historical
            # rows remain unassigned rather than inventing their pass identities.
            for pass_id, started in db.execute(
                "SELECT id,started FROM passes WHERE active=1"
            ):
                db.execute(
                    "UPDATE attempts SET pass_id=? "
                    "WHERE pass_id IS NULL AND started>=?",
                    (pass_id, started),
                )
        db.execute(
            "CREATE INDEX IF NOT EXISTS attempts_allocation ON attempts(pass_id)"
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        raise


def _metadata_available(db: sqlite3.Connection, pass_id: int, maximum: int) -> bool:
    used = db.execute(
        "SELECT COUNT(*) FROM attempts a JOIN work w ON w.id=a.work "
        "WHERE a.pass_id=? AND w.kind='search'",
        (pass_id,),
    ).fetchone()[0]
    available = max(0, maximum - used)
    db.execute(
        "INSERT OR IGNORE INTO pass_budget VALUES(?,?,?)",
        (pass_id, METADATA_BUDGET, available),
    )
    db.execute(
        "UPDATE pass_budget SET remaining=MIN(remaining,?) "
        "WHERE pass_id=? AND provider=?",
        (available, pass_id, METADATA_BUDGET),
    )
    remaining = db.execute(
        "SELECT remaining FROM pass_budget WHERE pass_id=? AND provider=?",
        (pass_id, METADATA_BUDGET),
    ).fetchone()[0]
    return bool(remaining > 0)


def _candidate_rows(
    db: sqlite3.Connection,
    kind: WorkKind,
    *,
    timestamp: float,
    pass_seconds: float,
    provider: str | None,
) -> Generator[sqlite3.Row, None, None]:
    parameters = (
        timestamp - pass_seconds,
        kind,
        timestamp,
        timestamp,
        timestamp,
        provider,
        provider,
    )
    if kind == "search":
        with closing(
            db.execute(
                _CANDIDATES
                + "AND w.priority>0 ORDER BY w.priority DESC,w.sequence,w.id",
                parameters,
            )
        ) as rows:
            yield from rows
        with closing(ordered_citation_candidates(db, _CANDIDATES, parameters)) as rows:
            yield from rows
    preferred = None
    if kind == "retrieve":
        claimed = db.execute(
            "SELECT claimed FROM retrieval_rotation WHERE id=1"
        ).fetchone()[0]
        preferred = preferred_retrieval_priority(claimed)
    if preferred is not None:
        # A narrow indexed lane avoids sorting the full backlog with a CASE key.
        with closing(
            db.execute(
                _CANDIDATES
                + "AND w.priority=? ORDER BY w.priority DESC,w.sequence,w.id",
                (*parameters, preferred),
            )
        ) as rows:
            yield from rows
    # Preferred work may be absent, delayed, leased, blocked or out of budget.
    # The ordinary order can still use the unchanged allowance in that case.
    with closing(
        db.execute(_CANDIDATES + "ORDER BY w.priority DESC,w.sequence,w.id", parameters)
    ) as rows:
        yield from rows


def claim_collection_work(
    db: sqlite3.Connection,
    kind: WorkKind,
    worker: str,
    *,
    now: datetime,
    provider: str | None,
    pass_seconds: float,
    lease_seconds: float,
    retained_refusals: dict[str, float],
    maximum_metadata_requests: int | None = None,
) -> ClaimedCollectionWork | None:
    """Claim work and advance fairness within the caller's transaction."""
    timestamp = now.timestamp()
    schedule = CollectionRequestSchedule(db, retained_refusals)
    with closing(
        _candidate_rows(
            db, kind, timestamp=timestamp, pass_seconds=pass_seconds, provider=provider
        )
    ) as rows:
        for row in rows:
            if schedule.ready_at(row) > timestamp:
                continue
            if row["attempts"] - row["policy_deferrals"] >= 4:
                db.execute(
                    "UPDATE work SET state='failed',outcome='attempts_exhausted',"
                    "detail='Worker lease expired after maximum attempts.' WHERE id=?",
                    (row["id"],),
                )
                continue
            budget_key = row["provider"] if kind == "search" else "article-retrieval"
            limit = row["budget"] if kind == "search" else row["budget"] * 4
            db.execute(
                "INSERT OR IGNORE INTO pass_budget VALUES(?,?,?)",
                (row["pass_id"], budget_key, limit),
            )
            remaining = db.execute(
                "SELECT remaining FROM pass_budget WHERE pass_id=? AND provider=?",
                (row["pass_id"], budget_key),
            ).fetchone()[0]
            if remaining <= 0:
                continue
            if kind == "search" and maximum_metadata_requests is not None:
                if not _metadata_available(
                    db, row["pass_id"], maximum_metadata_requests
                ):
                    # Viewers share this allocation. Do not traverse the entire
                    # backlog after its last global request was consumed.
                    return None
            token = worker + ":" + str(uuid4())
            db.execute(
                "UPDATE pass_budget SET remaining=remaining-1 WHERE "
                "pass_id=? AND provider=?",
                (row["pass_id"], budget_key),
            )
            db.execute(
                "UPDATE work SET state='leased',token=?,lease_until=?,"
                "attempts=attempts+1 WHERE id=?",
                (token, timestamp + lease_seconds, row["id"]),
            )
            db.execute(
                "INSERT INTO attempts(token,work,provider,started,pass_id) "
                "VALUES(?,?,?,?,?)",
                (token, row["id"], row["provider"], timestamp, row["pass_id"]),
            )
            if kind == "search" and maximum_metadata_requests is not None:
                db.execute(
                    "UPDATE pass_budget SET remaining=remaining-1 "
                    "WHERE pass_id=? AND provider=?",
                    (row["pass_id"], METADATA_BUDGET),
                )
            if kind == "search" and "citation_lane" in row.keys():
                db.execute(
                    "UPDATE citation_lanes SET claimed=claimed+1 WHERE id=?",
                    (row["citation_lane"],),
                )
            if kind == "retrieve":
                db.execute("UPDATE retrieval_rotation SET claimed=claimed+1 WHERE id=1")
            return ClaimedCollectionWork(
                row["id"],
                token,
                kind,
                row["provider"],
                PARTITION.validate_json(row["payload"]) if kind == "search" else None,
                LEAD.validate_json(row["payload"]) if kind == "retrieve" else None,
                row["attempts"] + 1,
                row["alternate_depth"],
                row["policy_deferrals"],
            )
    return None
