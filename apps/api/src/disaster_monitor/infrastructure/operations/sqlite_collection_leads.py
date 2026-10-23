"""Retained retrieval hints, priority migration, and richer rediscovery."""

import sqlite3
from hashlib import sha256

from pydantic import TypeAdapter

from disaster_monitor.application.ports.collection import ARTICLE_RETRIEVAL_PROVIDER
from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.news import NewsFeedItem

_LEAD = TypeAdapter(NewsFeedItem)
_PRIORITY_VERSION = 2


def initialize_retrieval_priorities(db: sqlite3.Connection) -> None:
    columns = {row[1] for row in db.execute("PRAGMA table_info(work)")}
    version = int(db.execute("PRAGMA user_version").fetchone()[0])
    if "priority" in columns and version >= _PRIORITY_VERSION:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        if "priority" not in columns:
            db.execute(
                "ALTER TABLE work ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
            )
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
    except BaseException:
        db.rollback()
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
