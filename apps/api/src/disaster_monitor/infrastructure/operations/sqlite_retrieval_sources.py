"""Durable retrieval turns for the observed metadata producers of a URL."""

import sqlite3
from collections.abc import Generator
from contextlib import closing

_SCHEMA = """
CREATE TABLE IF NOT EXISTS retrieval_sources (
  work TEXT NOT NULL, provider TEXT NOT NULL, PRIMARY KEY(work,provider)
);
CREATE TABLE IF NOT EXISTS retrieval_source_rotation (
  provider TEXT PRIMARY KEY, last_claimed INTEGER NOT NULL DEFAULT 0
);
"""


def initialize_retrieval_sources(db: sqlite3.Connection) -> None:
    existed = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='retrieval_sources'"
    ).fetchone()
    if existed:
        return
    db.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
    try:
        # Preserve all observed producers of shared work. Historical requests do
        # not acquire invented source assignments; rotation starts on adoption.
        # Visit edges first, avoiding a product of the two broad work-kind indexes.
        db.execute(
            "INSERT OR IGNORE INTO retrieval_sources "
            "SELECT child.id,parent.provider FROM work_links l "
            "CROSS JOIN work parent ON parent.id=l.parent "
            "CROSS JOIN work child ON child.id=l.child "
            "WHERE parent.kind='search' AND child.kind='retrieve'"
        )
        db.execute(
            "INSERT OR IGNORE INTO retrieval_source_rotation "
            "SELECT DISTINCT provider,0 FROM retrieval_sources"
        )
        if db.execute(
            "SELECT 1 FROM work w WHERE w.kind='retrieve' "
            "AND NOT EXISTS(SELECT 1 FROM retrieval_sources s WHERE s.work=w.id) "
            "LIMIT 1"
        ).fetchone():
            db.execute("INSERT OR IGNORE INTO retrieval_source_rotation VALUES('',0)")
        db.commit()
    except BaseException:
        db.rollback()
        raise


def register_retrieval_source(db: sqlite3.Connection, work: str, provider: str) -> None:
    db.execute("INSERT OR IGNORE INTO retrieval_sources VALUES(?,?)", (work, provider))
    db.execute(
        "INSERT OR IGNORE INTO retrieval_source_rotation VALUES(?,0)", (provider,)
    )


def ordered_retrieval_candidates(
    db: sqlite3.Connection, eligible_sql: str, parameters: tuple[object, ...]
) -> Generator[sqlite3.Row, None, None]:
    # Keep priority opportunities and the ordinary indexed queue order. Choose a
    # producer lane before reading its candidates, avoiding a sort of all saved
    # article payloads on every claim. A late or returning source receives one
    # turn, then waits for other ready sources; it does not catch up old totals.
    priorities = db.execute(
        "SELECT DISTINCT priority FROM work "
        "WHERE kind='retrieve' ORDER BY priority DESC"
    ).fetchall()
    sources = db.execute(
        "SELECT provider FROM retrieval_source_rotation ORDER BY last_claimed,provider"
    ).fetchall()
    for priority in priorities:
        for source in sources:
            if source["provider"]:
                scope = (
                    "AND EXISTS(SELECT 1 FROM retrieval_sources r "
                    "WHERE r.work=w.id AND r.provider=?) "
                )
                arguments = (*parameters, priority["priority"], source["provider"])
            else:
                # Empty source is reserved for legacy work without provenance.
                scope = (
                    "AND NOT EXISTS(SELECT 1 FROM retrieval_sources r "
                    "WHERE r.work=w.id) "
                )
                arguments = (*parameters, priority["priority"])
            with closing(
                db.execute(
                    eligible_sql
                    + "AND w.priority=? "
                    + scope
                    + "ORDER BY w.sequence,w.id",
                    arguments,
                )
            ) as rows:
                yield from rows


def record_retrieval_source_claim(db: sqlite3.Connection, work: str) -> None:
    # Shared work uses its least recently served actual producer. The work lease
    # and this ordinal update occur in the same claim transaction.
    row = db.execute(
        "SELECT s.provider FROM retrieval_sources s "
        "LEFT JOIN retrieval_source_rotation r ON r.provider=s.provider "
        "WHERE s.work=? ORDER BY COALESCE(r.last_claimed,0),s.provider LIMIT 1",
        (work,),
    ).fetchone()
    provider = row["provider"] if row else ""
    db.execute(
        "INSERT INTO retrieval_source_rotation "
        "SELECT ?,claimed+1 FROM retrieval_rotation WHERE id=1 "
        "ON CONFLICT(provider) DO UPDATE SET last_claimed=excluded.last_claimed",
        (provider,),
    )
