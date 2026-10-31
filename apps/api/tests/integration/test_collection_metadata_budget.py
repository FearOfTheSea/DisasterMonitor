"""Metadata providers share a durable total without borrowing publisher capacity."""

import asyncio
import sqlite3
from datetime import UTC, datetime

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


async def prepare(store, *, budget=2):
    interval = ReportingInterval.at_start(7, NOW)
    parts = tuple(
        CollectionPartition(f"index-{n}", "flood", interval.start, NOW)
        for n in range(7)
    )
    for n in range(5):
        await store.attach(
            DiscoveryRun(f"view-{n}", interval), parts, now=NOW, budget=budget
        )
    return parts


async def test_metadata_cap_is_atomic_shared_across_providers_views_and_restart(
    tmp_path,
):
    path = tmp_path / "collection.sqlite"
    store = SQLiteCollectionJournal(path, maximum_metadata_requests=3)
    await prepare(store)
    claimed = await asyncio.gather(
        *(
            store.claim("search", f"worker-{n}", now=NOW, provider=f"index-{n}")
            for n in range(7)
        )
    )
    work = [w for w in claimed if w is not None]
    assert len(work) == 3
    for w in work:
        assert await store.commit_page(w, CollectionPage(), now=NOW)
    restarted = SQLiteCollectionJournal(path, maximum_metadata_requests=3)
    assert await restarted.claim("search", "restart", now=NOW) is None
    assert await restarted.next_retry(now=NOW) is None
    snapshot = await restarted.snapshot("view-0", now=NOW)
    assert sum(n for _, n in snapshot.progress.provider_requests) == 3
    assert len(snapshot.progress.provider_requests) == 3
    await restarted.finish_pass(now=NOW)
    await restarted.continue_scan("view-0", now=NOW, budget=2, partitions=())
    assert await restarted.claim("search", "new-pass", now=NOW) is not None


async def test_total_metadata_cap_preserves_provider_limit_and_publisher_claims(
    tmp_path,
):
    store = SQLiteCollectionJournal(
        tmp_path / "collection.sqlite", maximum_metadata_requests=3
    )
    interval = ReportingInterval.at_start(1, NOW)
    parts = tuple(
        CollectionPartition("same-index", f"query-{n}", interval.start, NOW)
        for n in range(4)
    )
    await store.attach(DiscoveryRun("view", interval), parts, now=NOW, budget=2)
    first = await store.claim("search", "one", now=NOW)
    lead = NewsFeedItem(
        "local",
        "Regional Daily",
        "Flood aftermath",
        "https://daily.example/article",
        None,
        None,
    )
    assert await store.commit_page(first, CollectionPage(leads=(lead,)), now=NOW)
    second = await store.claim("search", "two", now=NOW)
    assert await store.commit_page(second, CollectionPage(), now=NOW)
    assert await store.claim("search", "provider-exhausted", now=NOW) is None
    publisher = await store.claim("retrieve", "publisher", now=NOW)
    assert publisher is not None and publisher.lead == lead


async def test_enabling_total_limit_midpass_accounts_for_already_spent_metadata(
    tmp_path,
):
    path = tmp_path / "collection.sqlite"
    old = SQLiteCollectionJournal(path)
    await prepare(old)
    for _ in range(2):
        work = await old.claim("search", "old-worker", now=NOW)
        assert await old.commit_page(work, CollectionPage(), now=NOW)
    bounded = SQLiteCollectionJournal(path, maximum_metadata_requests=3)
    last = await bounded.claim("search", "last", now=NOW)
    assert last is not None
    assert await bounded.commit_page(last, CollectionPage(), now=NOW)
    assert await bounded.claim("search", "no-extra", now=NOW) is None
    # A larger constructor value cannot replenish this existing allocation.
    changed = SQLiteCollectionJournal(path, maximum_metadata_requests=10)
    assert await changed.claim("search", "no-refill", now=NOW) is None


async def test_legacy_active_attempts_are_counted_before_the_first_new_claim(tmp_path):
    path = tmp_path / "legacy.sqlite"
    old = SQLiteCollectionJournal(path)
    await prepare(old)
    for _ in range(2):
        work = await old.claim("search", "old-worker", now=NOW)
        assert await old.commit_page(work, CollectionPage(), now=NOW)
    # Restore the actual pre-cap attempts-table shape to exercise migration.
    with sqlite3.connect(path) as db:
        db.execute("DROP INDEX attempts_allocation")
        db.execute("ALTER TABLE attempts DROP COLUMN pass_id")
    migrated = SQLiteCollectionJournal(path, maximum_metadata_requests=3)
    work = await migrated.claim("search", "new-worker", now=NOW)
    assert work is not None
    assert await migrated.commit_page(work, CollectionPage(), now=NOW)
    assert await migrated.claim("search", "exhausted", now=NOW) is None
