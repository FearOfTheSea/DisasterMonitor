"""Retained retrieval hints, priority migration, and richer rediscovery."""

import sqlite3
from hashlib import sha256

from pydantic import TypeAdapter

from disaster_monitor.application.ports.collection import ARTICLE_RETRIEVAL_PROVIDER
from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection_capacity import (
    is_storage_full,
)

_LEAD = TypeAdapter(NewsFeedItem)
# Bump when ranking rules change so retained work adopts the current policy.
_PRIORITY_VERSION = 6


def initialize_retrieval_priorities(
    db: sqlite3.Connection, *, priority_column_created: bool = False
) -> None:
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    if version >= _PRIORITY_VERSION and not priority_column_created:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        db.executemany(
            "UPDATE work SET priority=? WHERE id=?",
            (
                (
                    lead_retrieval_priority(_LEAD.validate_json(row["payload"])),
                    row["id"],
                )
                for row in db.execute(
                    "SELECT id,payload FROM work WHERE kind='retrieve' "
                    "AND state IN ('pending','leased','capacity')"
                ).fetchall()
            ),
        )
        db.execute(f"PRAGMA user_version={max(version, _PRIORITY_VERSION)}")
        db.commit()
    except BaseException as error:
        db.rollback()
        # Ordering upgrades must not hide retained evidence at full capacity.
        # Keep the old revision so the next open retries once space is available.
        if isinstance(error, sqlite3.Error) and is_storage_full(error):
            return
        raise


def enqueue_retrieval_lead(
    db: sqlite3.Connection, item: NewsFeedItem, generation: str
) -> str:
    key = sha256(
        ("retrieve|" + item.canonical_url + "|" + generation).encode()
    ).hexdigest()
    db.execute(
        "INSERT INTO work(id,kind,provider,payload,priority,sequence) "
        "VALUES(?,'retrieve',?,?,?,"
        "(SELECT COALESCE(MAX(sequence),0)+1 FROM work)) "
        "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,"
        "priority=excluded.priority "
        "WHERE work.state IN ('pending','leased','capacity') "
        "AND excluded.priority>work.priority",
        (
            key,
            ARTICLE_RETRIEVAL_PROVIDER,
            _LEAD.dump_json(item),
            lead_retrieval_priority(item),
        ),
    )
    return key
