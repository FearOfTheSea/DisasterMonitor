"""Durable search scheduling with initial coverage ahead of article follow-ups."""

import sqlite3
from dataclasses import replace

from pydantic import TypeAdapter

from disaster_monitor.domain.collection import (
    CollectionPartition,
    search_acquisition_priority,
)

_PARTITION = TypeAdapter(CollectionPartition)
_SEARCH_PRIORITY_VERSION = 3


def _scheduled(partition: CollectionPartition) -> CollectionPartition:
    return replace(
        partition,
        priority=search_acquisition_priority(
            alternate_for=partition.alternate_for,
            defer_initial_request=partition.defer_initial_request,
        ),
    )


def initialize_search_priorities(db: sqlite3.Connection) -> None:
    columns = {row[1] for row in db.execute("PRAGMA table_info(work)")}
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    if "priority" in columns and version >= _SEARCH_PRIORITY_VERSION:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        # Search scheduling precedes retrieval ranking migrations, so later
        # versions cannot skip the initial-versus-follow-up policy on old files.
        if "priority" not in columns:
            db.execute(
                "ALTER TABLE work ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
            )
        for row in db.execute(
            "SELECT id,payload FROM work WHERE kind='search' "
            "AND state IN ('pending','leased','capacity')"
        ).fetchall():
            partition = _scheduled(_PARTITION.validate_json(row["payload"]))
            db.execute(
                "UPDATE work SET priority=?,payload=? WHERE id=?",
                (partition.priority, _PARTITION.dump_json(partition), row["id"]),
            )
        db.execute(f"PRAGMA user_version={max(version, _SEARCH_PRIORITY_VERSION)}")
        db.commit()
    except BaseException:
        db.rollback()
        raise


def enqueue_search_partition(
    db: sqlite3.Connection, partition: CollectionPartition
) -> None:
    partition = _scheduled(partition)
    existing = db.execute(
        "SELECT payload,state FROM work WHERE id=?", (partition.key,)
    ).fetchone()
    if existing is not None and existing["state"] in ("pending", "leased", "capacity"):
        retained = _PARTITION.validate_json(existing["payload"])
        partition = replace(
            retained,
            retrieval_generation=partition.retrieval_generation
            or retained.retrieval_generation,
        )
    db.execute(
        "INSERT INTO work(id,kind,provider,payload,priority,sequence) "
        "VALUES(?,'search',?,?,?,(SELECT COALESCE(MAX(sequence),0)+1 FROM work)) "
        "ON CONFLICT(id) DO UPDATE SET priority=excluded.priority,"
        "payload=excluded.payload "
        "WHERE work.state IN ('pending','leased','capacity')",
        (
            partition.key,
            partition.provider,
            _PARTITION.dump_json(partition),
            partition.priority,
        ),
    )
