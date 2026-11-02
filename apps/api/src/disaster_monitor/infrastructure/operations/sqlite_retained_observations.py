"""Link an exact retained capture without a new publisher request or capture."""

import sqlite3
from datetime import datetime

from pydantic import TypeAdapter

from disaster_monitor.domain.collection_observation_reuse import can_reuse_observation
from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection_capacity import (
    is_storage_full,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_links import (
    link_collection_work,
)

_ARTICLE = TypeAdapter(DiscoveryArticle)
_LEAD = TypeAdapter(NewsFeedItem)


def initialize_retained_observation_lookup(db: sqlite3.Connection) -> bool:
    """Optional acceleration must not block retained reads when storage is full."""
    if not any(
        row[1] == "evidence_publisher_url"
        for row in db.execute("PRAGMA index_list(evidence)")
    ):
        return False
    try:
        db.execute(
            "CREATE INDEX IF NOT EXISTS work_evidence_capture ON "
            "work_evidence(evidence,work)"
        )
    except sqlite3.Error as error:
        if not is_storage_full(error):
            raise
        return False
    return True


def reuse_retained_observation(
    db: sqlite3.Connection, row: sqlite3.Row, *, now: datetime
) -> bool:
    """Only completed actual requests supply reuse; leases stay owned."""
    if row["state"] != "pending":
        return False
    lead = _LEAD.validate_json(row["payload"])
    latest: tuple[datetime, str, str] | None = None
    for saved in db.execute(
        # Start with this URL's captures. Otherwise SQLite can start from every
        # completed retrieval task for each individual pending observation.
        "SELECT e.id,e.article,w.payload,w.id FROM evidence e "
        "CROSS JOIN work_evidence we ON we.evidence=e.id "
        "CROSS JOIN work w ON w.id=we.work "
        "WHERE json_extract(e.article,'$.source.canonical_url')=? "
        "AND w.kind='retrieve' AND w.state='done' AND w.outcome='article_retrieved'",
        (lead.canonical_url,),
    ):
        article = _ARTICLE.validate_json(saved[1])
        retained_lead = _LEAD.validate_json(saved[2])
        if can_reuse_observation(lead, retained_lead, article, now=now):
            candidate = (article.source.retrieved_at, saved[0], saved[3])
            if latest is None or candidate > latest:
                latest = candidate
    if latest is None:
        return False
    # A reused body must not strand the original unresolved-headline follow-ups.
    children = db.execute(
        "SELECT child FROM work_links WHERE parent=?", (latest[2],)
    ).fetchall()
    for child in children:
        link_collection_work(db, row["id"], child[0])
    db.execute(
        "INSERT OR IGNORE INTO work_evidence(work,evidence) VALUES(?,?)",
        (row["id"], latest[1]),
    )
    db.execute(
        "UPDATE work SET state='done',outcome='retained_article_reused',"
        "detail='Retained capture reused for unchanged metadata; no "
        "publisher request.',"
        "token=NULL,lease_until=NULL WHERE id=?",
        (row["id"],),
    )
    return True
