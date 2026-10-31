"""Initial hazard coverage cannot be starved by a stream of article follow-ups."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.application.incidents.collection_planning import (
    plan_alternate_reports,
    plan_collection,
)
from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    CollectionPage,
    CollectionPartition,
)
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.bing_collection import (
    BingRssCollectionProvider,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 24, 9, tzinfo=UTC)
ROOT = CollectionPartition("controlled", "drought deaths", NOW - timedelta(days=1), NOW)
FOLLOWUP = replace(
    ROOT,
    query="An acquired headline",
    alternate_for="https://daily.example/story",
    priority=1,
)


async def prepare(path, partitions=(FOLLOWUP, ROOT)):
    store = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
    await store.attach(run, partitions, now=NOW, budget=20)
    return store, run


async def test_planned_initial_queries_precede_fatal_native_headline_followups():
    provider = BingRssCollectionProvider()
    try:
        roots = plan_collection(
            ReportingInterval.at_start(30, NOW), (provider,), observed_at=NOW
        )
        lead = NewsFeedItem(
            "n",
            "Daily",
            "Article title unavailable",
            "https://daily.example/story",
            None,
            None,
            search_title="Flood killed two people",
        )
        work = ClaimedCollectionWork(
            "w", "t", "retrieve", "publisher-articles", None, lead, 1
        )
        (followup,) = plan_alternate_reports(work, (provider,), observed_at=NOW)
        assert all(root.priority > followup.priority for root in roots)
        assert followup.alternate_for == lead.canonical_url
    finally:
        await provider.aclose()


async def test_initial_query_precedes_an_earlier_high_hint_followup(tmp_path):
    store, _ = await prepare(tmp_path / "journal.sqlite")
    first = await store.claim("search", "worker", now=NOW)
    assert first.partition.query == ROOT.query
    assert first.partition.alternate_for is None
    await store.commit_page(first, CollectionPage(), now=NOW)
    second = await store.claim("search", "worker", now=NOW)
    assert second.partition.alternate_for == FOLLOWUP.alternate_for


async def test_initial_query_continuation_is_not_overtaken_by_new_followups(tmp_path):
    store, run = await prepare(tmp_path / "journal.sqlite", (ROOT,))
    first = await store.claim("search", "worker", now=NOW)
    other = DiscoveryRun(str(uuid4()), run.interval)
    await store.attach(other, (FOLLOWUP,), now=NOW, budget=20)
    await store.commit_page(first, CollectionPage(next_cursor="relevance"), now=NOW)
    next_page = await store.claim("search", "worker", now=NOW)
    assert next_page.partition.alternate_for is None
    assert next_page.partition.cursor == "relevance"


@pytest.mark.parametrize("state", ["pending", "leased", "capacity"])
async def test_legacy_open_search_priorities_migrate_without_resetting_progress(
    tmp_path, state
):
    path = tmp_path / "journal.sqlite"
    store, _ = await prepare(path)
    await store.claim("search", "existing-lease", now=NOW)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        for partition in (ROOT, FOLLOWUP):
            old = replace(
                partition,
                priority=int(bool(partition.alternate_for)),
                cursor="relevance",
            )
            db.execute(
                "UPDATE work SET payload=?,priority=?,state=?,attempts=2,"
                "token='retained-token',lease_until=?,due=? WHERE id=?",
                (
                    json.dumps(
                        {
                            **json.loads(
                                db.execute(
                                    "SELECT payload FROM work WHERE id=?",
                                    (partition.key,),
                                ).fetchone()[0]
                            ),
                            "priority": old.priority,
                            "cursor": old.cursor,
                        }
                    ),
                    old.priority,
                    state,
                    NOW.timestamp() + 60,
                    NOW.timestamp() + 30,
                    partition.key,
                ),
            )
        db.execute("PRAGMA user_version=2")
        before = {r["id"]: dict(r) for r in db.execute("SELECT * FROM work")}
        budgets = db.execute("SELECT * FROM pass_budget").fetchall()
        scans = db.execute("SELECT * FROM scans").fetchall()
    SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        after = {r["id"]: dict(r) for r in db.execute("SELECT * FROM work")}
        assert after[ROOT.key]["priority"] > after[FOLLOWUP.key]["priority"]
        for key in before:
            assert {
                k: v for k, v in before[key].items() if k not in ("priority", "payload")
            } == {
                k: v for k, v in after[key].items() if k not in ("priority", "payload")
            }
            original, migrated = (
                json.loads(before[key]["payload"]),
                json.loads(after[key]["payload"]),
            )
            assert {k: v for k, v in original.items() if k != "priority"} == {
                k: v for k, v in migrated.items() if k != "priority"
            }
            assert migrated["priority"] == after[key]["priority"]
        assert db.execute("SELECT * FROM pass_budget").fetchall() == budgets
        assert db.execute("SELECT * FROM scans").fetchall() == scans
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        once = after
    SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert {r["id"]: dict(r) for r in db.execute("SELECT * FROM work")} == once


async def test_terminal_searches_remain_terminal_and_keep_their_original_payload(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    await prepare(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE work SET state='done',priority=0 WHERE id=?", (ROOT.key,))
        db.execute("PRAGMA user_version=2")
        before = db.execute("SELECT * FROM work WHERE id=?", (ROOT.key,)).fetchone()
    store = SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT * FROM work WHERE id=?", (ROOT.key,)).fetchone()
            == before
        )
    first = await store.claim("search", "worker", now=NOW)
    assert first.partition.alternate_for == FOLLOWUP.alternate_for


async def test_an_existing_lease_keeps_new_priority_when_committing_its_next_page(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    store, _ = await prepare(path, (ROOT,))
    leased = await store.claim("search", "old-worker", now=NOW)
    old = replace(leased, partition=replace(leased.partition, priority=0))
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")
        db.execute("UPDATE work SET priority=0")
    restarted = SQLiteCollectionJournal(path)
    assert await restarted.commit_page(
        old, CollectionPage(next_cursor="relevance"), now=NOW
    )
    with sqlite3.connect(path) as db:
        priority, payload = db.execute("SELECT priority,payload FROM work").fetchone()
        assert json.loads(payload)["priority"] == priority == 1
