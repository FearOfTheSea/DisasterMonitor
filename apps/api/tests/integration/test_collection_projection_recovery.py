"""A closed pass must not strand unprojected scans across process shutdown."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
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

NOW = datetime(2026, 10, 26, tzinfo=UTC)


class NoNetwork:
    source_id = "controlled"
    supports_alternates = False
    supports_time_filter = True
    queries = ("flood",)

    async def fetch_page(self, partition):
        pytest.fail("Projection recovery must not acquire another provider page.")

    async def retrieve(self, lead):
        pytest.fail("Projection recovery must not acquire a publisher article.")


@pytest.mark.parametrize("legacy_schema", [False, True])
async def test_restart_projects_closed_shared_pass_without_new_acquisition(
    tmp_path, legacy_schema
):
    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    runs = tuple(
        DiscoveryRun(str(day), ReportingInterval.at_start(day, NOW)) for day in (1, 3)
    )
    partition = CollectionPartition(
        "controlled", "flood", NOW - timedelta(hours=6), NOW
    )
    for run in runs:
        await store.attach(run, (partition,), now=NOW, budget=1)
    work = await store.claim("search", "reader", now=NOW)
    assert work is not None
    source = SourceReference(
        "controlled",
        "Regional News",
        "Fatal flood",
        "https://news.example/flood",
        NOW,
        None,
        NOW,
    )
    await store.commit_page(
        work,
        CollectionPage(
            articles=(DiscoveryArticle(source, "Two people died in the flood."),),
            leads=(
                NewsFeedItem(
                    "pending",
                    "Other News",
                    "Flood report",
                    "https://other.example/flood",
                    None,
                    None,
                    NOW,
                ),
            ),
        ),
        now=NOW,
    )
    await store.finish_pass(now=NOW)
    for run in runs:
        assert (await store.read(run.scan_id)).status == "running"
    with sqlite3.connect(path) as db:
        if legacy_schema:
            columns = {row[1] for row in db.execute("PRAGMA table_info(scans)")}
            if "projection_pending" in columns:
                db.execute("ALTER TABLE scans DROP COLUMN projection_pending")
        attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    restarted = SQLiteCollectionJournal(path)
    service = ResumableDiscovery(
        (NoNetwork(),), NoNetwork(), restarted, clock=lambda: NOW
    )
    try:
        await service.recover()
        await service.wait(runs[0].scan_id)
        for run in runs:
            result = await service.get(run.scan_id)
            assert result.status == "incomplete"
            assert result.interval == run.interval
            assert result.collection.can_continue
            assert result.collection.articles_pending == 1
            assert result.collection.provider_requests == (("controlled", 1),)
            assert any(
                c.fact.category == "fatalities"
                for r in result.reports
                for m in r.mentions
                for c in m.claims
            )
        assert not await restarted.active_scans()
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT COUNT(*),SUM(active) FROM passes").fetchone() == (
                1,
                0,
            )
            assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == attempts
    finally:
        await service.aclose()


@pytest.mark.parametrize("capacity_stopped", [False, True])
async def test_legacy_terminal_or_capacity_stopped_scan_is_not_resurrected(
    tmp_path, capacity_stopped
):
    from dataclasses import replace

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    run = DiscoveryRun("terminal", ReportingInterval.at_start(1, NOW))
    partition = CollectionPartition(
        "controlled", "flood", NOW - timedelta(hours=6), NOW
    )
    await store.attach(run, (partition,), now=NOW, budget=1)
    if capacity_stopped:
        await store.suspend_at_capacity(now=NOW)
    else:
        await store.finish_pass(now=NOW)
        await store.save(replace(run, status="completed"))
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE scans DROP COLUMN projection_pending")
    restarted = SQLiteCollectionJournal(path)
    assert not await restarted.active_scans()
    result = await restarted.read(run.scan_id)
    assert result.status == ("incomplete" if capacity_stopped else "completed")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*),SUM(active) FROM passes").fetchone() == (
            1,
            0,
        )
