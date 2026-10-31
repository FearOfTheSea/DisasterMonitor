"""Repeated index sightings must not accumulate hydrated page copies in projections."""

import gc
import tracemalloc
from dataclasses import replace
from datetime import UTC, datetime

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


async def test_duplicate_index_pages_keep_projection_memory_bounded(tmp_path):
    journal = SQLiteCollectionJournal(tmp_path / "collection.sqlite")
    run = DiscoveryRun("memory", ReportingInterval.at_start(1, NOW))
    partition = CollectionPartition("index", "flood", run.interval.start, NOW)
    await journal.attach(run, (partition,), now=NOW, budget=100)
    first = NewsFeedItem(
        "article",
        "Publisher",
        "Flood reporting",
        "https://publisher.example/0",
        None,
        None,
    )
    leads = tuple(
        replace(
            first,
            canonical_url=f"https://publisher.example/{i}",
            title=f"Flood report {i} " + "original publisher wording " * 40,
        )
        for i in range(100)
    )

    async def append_page(index):
        work = await journal.claim("search", "index-reader", now=NOW)
        assert work is not None
        assert await journal.commit_page(
            work,
            CollectionPage(
                leads=leads,
                next_cursor=str(index + 1),
                notices=("Publisher coverage is partial.",),
            ),
            now=NOW,
        )

    async def measured_snapshot():
        gc.collect()
        tracemalloc.start()
        try:
            snapshot = await journal.snapshot(run.scan_id, now=NOW)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert set(snapshot.leads) == set(leads)
        assert snapshot.progress.leads_acquired == len(leads)
        assert snapshot.progress.notices == ("Publisher coverage is partial.",)
        return snapshot.progress.pages_acquired, peak

    for index in range(2):
        await append_page(index)
    small_pages, small_peak = await measured_snapshot()
    for index in range(2, 40):
        await append_page(index)
    large_pages, large_peak = await measured_snapshot()
    assert (small_pages, large_pages) == (2, 40)
    # Unique leads and output are fixed. Allow ample allocator/thread overhead,
    # but not the twentyfold growth from retaining forty decoded index pages.
    assert large_peak < small_peak * 3 + 1024 * 1024


async def test_page_context_keeps_ordered_supplemental_versions_and_scan_scope(
    tmp_path,
):
    journal = SQLiteCollectionJournal(tmp_path / "context.sqlite")
    run = DiscoveryRun("context", ReportingInterval.at_start(1, NOW))
    other = replace(run, scan_id="other")
    partition = CollectionPartition("index", "flood", run.interval.start, NOW)
    await journal.attach(run, (partition,), now=NOW, budget=10)
    await journal.attach(other, (), now=NOW, budget=10)
    article = DiscoveryArticle(
        SourceReference(
            "news",
            "Publisher",
            "Original account",
            "https://publisher.example/a",
            NOW,
            None,
            NOW,
        ),
        "Original qualified account.",
        origin="Reporting agency",
        original_url="https://agency.example/original",
        bylines=("First reporter",),
    )
    revised = replace(article, text="Revised account; toll remains disputed.")
    for index, records in enumerate(((article,), (article, revised))):
        work = await journal.claim("search", "index-reader", now=NOW)
        assert work is not None
        assert await journal.commit_page(
            work,
            CollectionPage(
                supplemental=records,
                notices=("First notice", f"Page {index}"),
                next_cursor="next" if index == 0 else None,
            ),
            now=NOW,
        )
    snapshot = await journal.snapshot(run.scan_id, now=NOW)
    assert snapshot.supplemental == (article, article, revised)
    assert snapshot.progress.pages_acquired == 2
    assert snapshot.progress.notices == ("First notice", "Page 0", "Page 1")
    unrelated = await journal.snapshot(other.scan_id, now=NOW)
    assert unrelated.supplemental == ()
    assert unrelated.progress.pages_acquired == 0
    assert unrelated.progress.notices == ()
