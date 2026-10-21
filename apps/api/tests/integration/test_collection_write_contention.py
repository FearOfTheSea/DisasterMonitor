"""A journal's own admitted writes queue instead of exhausting SQLite's busy wait."""

import asyncio
from datetime import UTC, datetime
from threading import Event

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)


async def test_claim_waits_for_this_journals_admitted_write_without_losing_work(
    tmp_path,
):
    journal = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    run = DiscoveryRun("controlled", ReportingInterval.at_start(1, NOW))
    partition = CollectionPartition("controlled", "flood", run.interval.start, NOW)
    await journal.attach(run, (partition,), now=NOW, budget=1)
    holding = Event()
    release = Event()

    def hold_admitted_transaction():
        # Exercise contention inside this adapter's transaction boundary. An
        # external process still has SQLite's separate, bounded busy timeout.
        with journal._transaction():
            holding.set()
            assert release.wait(20)

    holder = asyncio.create_task(asyncio.to_thread(hold_admitted_transaction))
    pending = None
    try:
        assert await asyncio.to_thread(holding.wait, 1)
        pending = asyncio.create_task(
            journal.claim("search", "second", now=NOW, provider="controlled")
        )
        # Connection configuration and BEGIN can each wait five seconds. A
        # journal's own queued write must survive both without losing work.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(pending), 11)
        release.set()
        await holder
        work = await asyncio.wait_for(pending, 2)
        assert work and work.attempts == 1
        assert work.partition == partition
        assert await journal.commit_page(work, CollectionPage(), now=NOW)
        assert await journal.claim("search", "third", now=NOW) is None
        assert (
            await journal.snapshot(run.scan_id, now=NOW)
        ).progress.pages_acquired == 1
    finally:
        release.set()
        await holder
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
