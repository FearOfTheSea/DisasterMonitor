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
        priority=search_acquisition_priority(alternate_for=partition.alternate_for),
    )


def initialize_search_priorities(db: sqlite3.Connection) -> None:
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    if version >= _SEARCH_PRIORITY_VERSION:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
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
    db.execute(
        "INSERT INTO work(id,kind,provider,payload,priority,sequence) "
        "VALUES(?,'search',?,?,?,(SELECT COALESCE(MAX(sequence),0)+1 FROM work)) "
        "ON CONFLICT(id) DO UPDATE SET priority=excluded.priority "
        "WHERE work.state IN ('pending','leased','capacity')",
        (
            partition.key,
            partition.provider,
            _PARTITION.dump_json(partition),
            partition.priority,
        ),
    )
