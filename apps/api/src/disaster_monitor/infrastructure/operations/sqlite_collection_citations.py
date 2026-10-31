"""Durable citation-source diversity; index ordering never supplies article facts."""

import sqlite3
from itertools import groupby

from pydantic import TypeAdapter

from disaster_monitor.domain.collection import CollectionPartition

_PARTITION = TypeAdapter(CollectionPartition)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS citation_lanes (
 id INTEGER PRIMARY KEY, provider TEXT NOT NULL, family TEXT NOT NULL,
 window_start REAL NOT NULL, claimed INTEGER NOT NULL DEFAULT 0,
 source_order INTEGER NOT NULL,
 UNIQUE(provider,family,window_start)
);
CREATE TABLE IF NOT EXISTS citation_work (
 work TEXT NOT NULL, lane INTEGER NOT NULL, position INTEGER NOT NULL,
 PRIMARY KEY(work,lane)
);
CREATE INDEX IF NOT EXISTS citation_lane_members ON citation_work(lane,position,work);
"""


def register_citation_page(
    db: sqlite3.Connection,
    parent_id: str,
    parent: CollectionPartition,
    children: tuple[CollectionPartition, ...],
) -> None:
    citations = [
        (i, child) for i, child in enumerate(children) if child.defer_initial_request
    ]
    if not citations:
        return
    sequence = db.execute(
        "SELECT sequence FROM work WHERE id=?", (parent_id,)
    ).fetchone()[0]
    key = (parent.provider, parent.query, parent.start.timestamp())
    db.execute(
        "INSERT INTO citation_lanes(provider,family,window_start,source_order) "
        "VALUES(?,?,?,?) ON CONFLICT(provider,family,window_start) DO UPDATE "
        "SET source_order=MIN(source_order,excluded.source_order)",
        (*key, sequence),
    )
    lane = db.execute(
        "SELECT id FROM citation_lanes WHERE provider=? AND family=? "
        "AND window_start=?",
        key,
    ).fetchone()[0]
    db.executemany(
        "INSERT INTO citation_work VALUES(?,?,?) ON CONFLICT(work,lane) DO UPDATE "
        "SET position=MIN(position,excluded.position)",
        ((child.key, lane, position) for position, child in citations),
    )


def initialize_citation_schedule(db: sqlite3.Connection) -> None:
    existed = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='citation_lanes'"
    ).fetchone()
    try:
        db.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        if existed:
            db.commit()
            return
        # Existing keys, leases, attempts, cursors and budgets are retained. Legacy
        # unstarted citations acquire source routing from their actual graph links;
        # old completed work is not assigned invented historical fairness counts.
        rows = db.execute(
            "SELECT p.id,p.payload AS parent,c.payload AS child FROM work_links l "
            "JOIN work p ON p.id=l.parent JOIN work c ON c.id=l.child "
            "WHERE c.kind='search' AND c.state IN ('pending','leased','capacity') "
            "AND json_extract(c.payload,'$.defer_initial_request')=1 "
            "ORDER BY p.id,c.sequence,c.id"
        )
        for parent_id, group in groupby(rows, key=lambda row: row["id"]):
            members = list(group)
            register_citation_page(
                db,
                parent_id,
                _PARTITION.validate_json(members[0]["parent"]),
                tuple(_PARTITION.validate_json(row["child"]) for row in members),
            )
        db.commit()
    except BaseException:
        db.rollback()
        raise


def ordered_citation_candidates(
    db: sqlite3.Connection, eligible_sql: str, parameters: tuple[object, ...]
) -> sqlite3.Cursor:
    # Small source counters are aggregated once; eligible work still obeys the
    # caller's active-view, lease, due-time, provider and cooldown constraints.
    # Balance query families, then publication weeks, then their individual route.
    # Within equal routes preserve initial source order and the RSS index rank.
    return db.execute(
        "WITH eligible AS (" + eligible_sql + " AND w.priority=0), "
        "families AS (SELECT provider,family,SUM(claimed) AS used,"
        "MIN(source_order) AS first_seen FROM citation_lanes "
        "GROUP BY provider,family), "
        "windows AS (SELECT provider,window_start,SUM(claimed) AS used "
        "FROM citation_lanes GROUP BY provider,window_start) "
        "SELECT e.*,l.id AS citation_lane FROM eligible e "
        "JOIN citation_work c ON c.work=e.id JOIN citation_lanes l ON l.id=c.lane "
        "JOIN families f ON f.provider=l.provider AND f.family=l.family "
        "JOIN windows t ON t.provider=l.provider AND t.window_start=l.window_start "
        "ORDER BY f.used,t.used,l.claimed,f.first_seen,l.window_start,c.position,e.id",
        parameters,
    )
