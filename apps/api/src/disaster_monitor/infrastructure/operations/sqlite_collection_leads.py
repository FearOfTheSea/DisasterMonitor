"""Retained retrieval hints, priority migration, and richer rediscovery."""

import sqlite3
from dataclasses import replace
from hashlib import sha256

from pydantic import TypeAdapter

from disaster_monitor.application.ports.collection import ARTICLE_RETRIEVAL_PROVIDER
from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    lead_retrieval_priority,
)
from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection_capacity import (
    CollectionLeadBudget,
    is_storage_full,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_links import (
    link_collection_work,
)
from disaster_monitor.infrastructure.operations.sqlite_retrieval_sources import (
    register_retrieval_source,
)

_LEAD = TypeAdapter(NewsFeedItem)
# Bump when ranking rules change so retained work adopts the current policy.
_PRIORITY_VERSION = 7


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


def retrieval_work_key(url: str, generation: str) -> str:
    return sha256(f"retrieve|{url}|{generation}".encode()).hexdigest()


def referring_retrieval_generation(
    db: sqlite3.Connection, work: ClaimedCollectionWork
) -> str:
    assert work.lead is not None
    for (generation,) in db.execute(
        "SELECT COALESCE(json_extract(w.payload,'$.retrieval_generation'),"
        "json_extract(w.payload,'$.generation')) FROM work_links l "
        "JOIN work w ON w.id=l.parent WHERE l.child=? AND w.kind='search'",
        (work.work_id,),
    ):
        if (
            generation is not None
            and retrieval_work_key(work.lead.canonical_url, generation) == work.work_id
        ):
            return generation
    # A legacy or restamped root may no longer expose this lease's generation.
    # Keep its descendants stable for subsequent viewers of this same capture.
    return f"publisher-reference:{work.work_id}"


def enqueue_retrieval_lead(
    db: sqlite3.Connection, item: NewsFeedItem, generation: str
) -> str:
    key = retrieval_work_key(item.canonical_url, generation)
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


def index_retrieval_lead(
    db: sqlite3.Connection,
    parent: str,
    item: NewsFeedItem,
    generation: str,
    producer: str,
) -> str:
    db.execute(
        "INSERT OR IGNORE INTO leads VALUES(?,?)",
        (item.canonical_url, _LEAD.dump_json(item)),
    )
    db.execute(
        "INSERT OR IGNORE INTO work_leads VALUES(?,?)",
        (parent, item.canonical_url),
    )
    key = enqueue_retrieval_lead(db, item, generation)
    link_collection_work(db, parent, key)
    register_retrieval_source(db, key, producer)
    return key


def link_publisher_documents(
    db: sqlite3.Connection,
    work: ClaimedCollectionWork,
    article: DiscoveryArticle,
    lead_budget: CollectionLeadBudget,
) -> str | None:
    if work.lead is None or work.lead.referring_document_url is not None:
        return None
    links = tuple(
        lead
        for lead in article.document_leads[:2]
        if lead.referring_document_url is not None
        and lead.canonical_url != work.lead.canonical_url
    )
    if not links:
        return None
    producer = "publisher-document-links"
    refusal = lead_budget.page_refusal(
        db, producer, {lead.canonical_url for lead in links}, 0
    )
    if refusal:
        return "Publisher report links exceed available collection capacity."
    generation = referring_retrieval_generation(db, work)
    for lead in links:
        saved = db.execute(
            "SELECT payload FROM work WHERE id=?",
            (retrieval_work_key(lead.canonical_url, generation),),
        ).fetchone()
        if saved:
            existing = _LEAD.validate_json(saved[0])
            lead = replace(existing, referring_document_url=lead.referring_document_url)
        key = index_retrieval_lead(db, work.work_id, lead, generation, producer)
        if work.alternate_depth and saved is None:
            db.execute("UPDATE work SET alternate_depth=1 WHERE id=?", (key,))
    return None
