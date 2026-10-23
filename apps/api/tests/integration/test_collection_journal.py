"""Real SQLite behavior at the durable acquisition boundary."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


def partition(provider="news", query="flood"):
    return CollectionPartition(provider, query, NOW - timedelta(days=1), NOW)


def run():
    return DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))


def lead():
    return NewsFeedItem(
        "one",
        "Publisher",
        "Flood in Riverton",
        "https://publisher.example/one",
        None,
        None,
        NOW,
    )


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "title", ["Four killed in forest fire", "Staffing gaps during deadly flood"]
)
async def test_fatality_hints_get_retrieval_priority_without_dropping_routine_work(
    tmp_path,
    legacy,
    title,
):
    path = tmp_path / "jobs.sqlite"
    store = SQLiteCollectionJournal(path)
    await store.attach(run(), (partition(),), now=NOW, budget=10)
    search = await store.claim("search", "searcher", now=NOW)
    routine = lead()
    fatal = replace(
        routine,
        external_id="fatal",
        canonical_url="https://another.example/fatal",
        title=title,
    )
    await store.commit_page(search, CollectionPage(leads=(routine, fatal)), now=NOW)
    if legacy:
        with sqlite3.connect(path) as db:
            db.execute("ALTER TABLE work DROP COLUMN priority")
        store = SQLiteCollectionJournal(path)
    first = await store.claim("retrieve", "reader", now=NOW)
    second = await store.claim("retrieve", "other-reader", now=NOW)
    assert first.lead == fatal
    assert second.lead == routine


async def test_page_and_cursor_survive_restart_with_shared_work_and_no_duplicates(
    tmp_path,
):
    path = tmp_path / "jobs.sqlite"
    store = SQLiteCollectionJournal(path)
    first, second = run(), run()
    await store.attach(first, (partition(),), now=NOW, budget=10)
    await store.attach(second, (partition(),), now=NOW, budget=10)
    claimed = await store.claim("search", "worker", now=NOW)
    assert claimed is not None
    page = CollectionPage(leads=(lead(),), next_cursor="20")
    assert await store.commit_page(claimed, page, now=NOW)
    assert not await store.commit_page(claimed, page, now=NOW)
    restarted = SQLiteCollectionJournal(path)
    next_job = await restarted.claim("search", "new-worker", now=NOW)
    assert next_job.partition.cursor == "20"
    assert await restarted.commit_page(next_job, CollectionPage(), now=NOW)
    for scan in (first, second):
        snapshot = await restarted.snapshot(scan.scan_id, now=NOW)
        assert len(snapshot.leads) == 1
        assert snapshot.progress.searches_completed == 1
        assert snapshot.progress.pages_acquired == 2
    assert await restarted.claim("search", "other", now=NOW) is None


async def test_expired_lease_fences_stale_writer_and_claims_are_exclusive(tmp_path):
    store = SQLiteCollectionJournal(tmp_path / "jobs.sqlite", lease_seconds=10)
    await store.attach(run(), (partition(),), now=NOW, budget=10)
    claims = await asyncio.gather(
        *(store.claim("search", str(i), now=NOW) for i in range(10))
    )
    old = next(c for c in claims if c)
    assert sum(c is not None for c in claims) == 1
    current = await store.claim(
        "search", "replacement", now=NOW + timedelta(seconds=11)
    )
    assert current is not None
    assert not await store.commit_page(
        old, CollectionPage(leads=(lead(),)), now=NOW + timedelta(seconds=11)
    )
    assert await store.commit_page(
        current, CollectionPage(), now=NOW + timedelta(seconds=11)
    )


async def test_provider_cooldown_survives_continue_and_restart_without_blocking_others(
    tmp_path,
):
    path = tmp_path / "jobs.sqlite"
    store = SQLiteCollectionJournal(path)
    scan = run()
    await store.attach(
        scan, (partition("blocked"), partition("healthy")), now=NOW, budget=10
    )
    blocked = await store.claim("search", "a", now=NOW)
    retry = NOW + timedelta(hours=1)
    await store.fail(
        blocked, outcome="rate_limited", detail="HTTP 429", now=NOW, retry_at=retry
    )
    healthy = await store.claim("search", "b", now=NOW)
    assert healthy.partition.provider == "healthy"
    await store.commit_page(healthy, CollectionPage(), now=NOW)
    await store.finish_pass(now=NOW)
    restarted = SQLiteCollectionJournal(path)
    await restarted.continue_scan(scan.scan_id, now=NOW, budget=10)
    assert await restarted.claim("search", "c", now=NOW) is None
    assert (await restarted.snapshot(scan.scan_id, now=NOW)).progress.retry_at == retry
    assert await restarted.claim("search", "c", now=retry) is None
    await restarted.finish_pass(now=retry)
    await restarted.continue_scan(scan.scan_id, now=retry, budget=10)
    assert await restarted.claim("search", "c", now=retry) is not None


async def test_budget_defers_cursor_instead_of_losing_pending_work(tmp_path):
    store = SQLiteCollectionJournal(tmp_path / "jobs.sqlite")
    scan = run()
    await store.attach(scan, (partition(),), now=NOW, budget=1)
    work = await store.claim("search", "a", now=NOW)
    await store.commit_page(work, CollectionPage(next_cursor="next"), now=NOW)
    assert await store.claim("search", "b", now=NOW) is None
    await store.finish_pass(now=NOW)
    assert (await store.snapshot(scan.scan_id, now=NOW)).progress.searches_pending == 1
    await store.continue_scan(scan.scan_id, now=NOW, budget=1)
    assert (await store.claim("search", "b", now=NOW)).partition.cursor == "next"


async def test_failed_page_is_not_acknowledged_and_refusal_is_distinct_from_empty(
    tmp_path,
):
    store = SQLiteCollectionJournal(tmp_path / "jobs.sqlite")
    scan = run()
    await store.attach(
        scan, (partition("refused"), partition("empty")), now=NOW, budget=10
    )
    work = await store.claim("search", "a", now=NOW)
    await store.fail(work, outcome="access_refused", detail="HTTP 403", now=NOW)
    work = await store.claim("search", "b", now=NOW)
    await store.commit_page(work, CollectionPage(), now=NOW)
    progress = (await store.snapshot(scan.scan_id, now=NOW)).progress
    assert progress.searches_completed == 1
    assert progress.searches_refused == 1
    assert progress.pages_acquired == 1


async def test_invalid_page_rolls_back_evidence_and_continuation(tmp_path):
    path = tmp_path / "jobs.sqlite"
    store = SQLiteCollectionJournal(path)
    scan = run()
    await store.attach(scan, (partition(),), now=NOW, budget=10)
    work = await store.claim("search", "a", now=NOW)
    report = DiscoveryArticle(
        SourceReference(
            "publisher",
            "Publisher",
            "Flood",
            "https://publisher.example/report",
            NOW,
            None,
            NOW,
        ),
        "Two people died in the flood.",
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TRIGGER fail_evidence BEFORE INSERT ON evidence "
            "BEGIN SELECT RAISE(ABORT,'controlled write failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="controlled write failure"):
        await store.commit_page(
            work,
            CollectionPage(leads=(lead(),), articles=(report,), next_cursor="next"),
            now=NOW,
        )
    snapshot = await store.snapshot(scan.scan_id, now=NOW)
    assert not snapshot.leads and not snapshot.articles
    assert snapshot.progress.pages_acquired == 0
    later = NOW + timedelta(seconds=91)
    resumed = await store.claim("search", "restart", now=later)
    assert resumed.partition.cursor == ""


async def test_historical_file_scan_links_and_evidence_remain_readable(tmp_path):
    from disaster_monitor.infrastructure.operations.file_discovery_store import (
        FileDiscoveryStore,
    )

    legacy = FileDiscoveryStore(tmp_path / "historical")
    historical = run()
    await legacy.save(historical)
    store = SQLiteCollectionJournal(tmp_path / "jobs.sqlite", legacy=legacy)
    assert await store.read(historical.scan_id) == historical
    assert historical in await store.recent()
    assert (tmp_path / "historical" / f"{historical.scan_id}.json").exists()


async def test_capacity_preserves_unacknowledged_page_for_a_later_configured_limit(
    tmp_path,
):
    from dataclasses import replace

    path = tmp_path / "jobs.sqlite"
    store = SQLiteCollectionJournal(path, maximum_leads=1)
    scan = run()
    await store.attach(scan, (partition(),), now=NOW, budget=10)
    work = await store.claim("search", "a", now=NOW)
    page = CollectionPage(
        leads=(lead(), replace(lead(), canonical_url="https://publisher.example/two")),
        next_cursor="next",
    )
    assert not await store.commit_page(work, page, now=NOW)
    snapshot = await store.snapshot(scan.scan_id, now=NOW)
    assert snapshot.progress.can_continue
    assert snapshot.progress.pages_acquired == 0
    assert not snapshot.leads
    await store.finish_pass(now=NOW)
    configured = SQLiteCollectionJournal(path, maximum_leads=10)
    await configured.continue_scan(scan.scan_id, now=NOW, budget=10)
    resumed = await configured.claim("search", "b", now=NOW)
    assert resumed.partition.cursor == ""
    assert await configured.commit_page(resumed, page, now=NOW)
