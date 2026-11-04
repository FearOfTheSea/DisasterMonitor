"""Large index frontiers must expose publishers within ordinary request caps."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 11, 4, 8, tzinfo=UTC)


async def test_large_frontier_interleaves_publishers_and_survives_reopen(tmp_path):
    path = tmp_path / "journal.sqlite"
    roots = tuple(
        CollectionPartition("index", f"query-{i}", NOW - timedelta(days=30), NOW)
        for i in range(1340)
    )
    store = SQLiteCollectionJournal(path, maximum_metadata_requests=200)
    run = DiscoveryRun("month", ReportingInterval.at_start(30, NOW))
    await store.attach(run, roots, now=NOW, budget=200)
    indexed, resolved = [], []
    for allocation in range(2):
        if allocation:
            await store.finish_pass(now=NOW)
            await store.continue_scan(run.scan_id, now=NOW, budget=200)
        for request in range(200):
            # Reopening must retain the request rotation and citation progress.
            if request % 17 == 0:
                store = SQLiteCollectionJournal(path, maximum_metadata_requests=200)
            work = await store.claim("search", "index", now=NOW, provider="index")
            assert work is not None
            partition = work.partition
            if partition.query.startswith("query-"):
                indexed.append(partition.query)
                child = replace(
                    partition,
                    query="citation-" + partition.query,
                    depth=1,
                    defer_initial_request=True,
                    shared_resource=True,
                )
                page = CollectionPage(children=(child,))
            elif not partition.cursor:
                page = CollectionPage(next_cursor="publisher-resolution")
            else:
                resolved.append(partition.query)
                page = CollectionPage(
                    leads=(
                        NewsFeedItem(
                            partition.query,
                            "Daily",
                            "Flood killed two people",
                            "https://daily.example/" + partition.query,
                            None,
                            None,
                        ),
                    )
                )
            assert await store.commit_page(work, page, now=NOW)
        assert await store.claim("search", "over-cap", now=NOW) is None
        assert len(indexed) >= 50 * (allocation + 1)
        assert len(resolved) >= 50 * (allocation + 1)
    assert len(set(indexed)) == len(indexed)
    snapshot = await store.snapshot(run.scan_id, now=NOW)
    assert len(snapshot.leads) == len(resolved)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 400
        assert db.execute(
            "SELECT COUNT(*) FROM work WHERE kind='search' "
            "AND json_extract(payload,'$.query') LIKE 'query-%'"
        ).fetchone()[0] == len(roots)
