"""Large projections retain complete evidence within physical storage limits."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

from pydantic import TypeAdapter

from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)
LIMIT = 1024 * 1024


def large_run(scan_id):
    return DiscoveryRun(
        scan_id,
        ReportingInterval.at_start(30, NOW),
        issues=("Retained publisher passage and attribution. " * 30_000,),
    )


async def test_large_repetitive_projection_round_trips_through_all_journal_operations(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    original = large_run("large")
    await journal.attach(original, (), now=NOW, budget=1)
    assert await journal.read(original.scan_id) == original
    assert (await journal.snapshot(original.scan_id, now=NOW)).run == original
    await journal.continue_scan(original.scan_id, now=NOW, budget=1)
    assert await journal.read(original.scan_id) == original
    changed = replace(original, status="incomplete", finished_at=NOW)
    await journal.save(changed)
    restarted = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    assert await restarted.read(original.scan_id) == changed
    assert await restarted.recent() == (changed,)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            db.execute("PRAGMA page_count").fetchone()[0]
            * db.execute("PRAGMA page_size").fetchone()[0]
        ) <= LIMIT


async def test_legacy_plain_json_projection_remains_readable_and_can_continue(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path, maximum_bytes=4 * LIMIT)
    original = large_run("legacy")
    await journal.attach(replace(original, issues=()), (), now=NOW, budget=1)
    # Simulate the existing on-disk encoding, independently of the new writer.
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE scans SET run=? WHERE id=?",
            (TypeAdapter(DiscoveryRun).dump_json(original), original.scan_id),
        )
    assert await journal.read(original.scan_id) == original
    assert (await journal.snapshot(original.scan_id, now=NOW)).run == original
    assert await journal.recent() == (original,)
    await journal.continue_scan(original.scan_id, now=NOW, budget=1)
    assert await SQLiteCollectionJournal(path).read(original.scan_id) == original


async def test_ten_concurrent_large_projection_writes_preserve_every_scan(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    runs = tuple(large_run(f"user-{index}") for index in range(10))
    results = await asyncio.gather(
        *(journal.save(run) for run in runs), return_exceptions=True
    )
    assert results == [None] * len(runs)
    assert {r.scan_id for r in await journal.recent()} == {r.scan_id for r in runs}
    restarted = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    assert await asyncio.gather(*(restarted.read(run.scan_id) for run in runs)) == list(
        runs
    )
