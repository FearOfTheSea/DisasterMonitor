"""Accepted scans must survive the preceding worker's final projection."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
from disaster_monitor.domain.collection import CollectionSnapshot
from disaster_monitor.domain.discovery import CollectionProgress

NOW = datetime(2026, 10, 20, tzinfo=UTC)


class CheckpointJournal:
    """In-memory journal with an operator-visible final-save checkpoint."""

    def __init__(self):
        self.runs = {}
        self.active = set()
        self.finished = asyncio.Event()
        self.release = asyncio.Event()
        self.second_finished = asyncio.Event()
        self.pass_count = 0

    async def attach(self, run, partitions, *, now, budget):
        self.runs[run.scan_id] = run
        self.active.add(run.scan_id)

    async def continue_scan(self, scan_id, *, now, budget):
        self.active.add(scan_id)
        self.runs[scan_id] = replace(self.runs[scan_id], status="running")

    async def read(self, scan_id):
        return self.runs.get(scan_id)

    async def active_scans(self):
        return tuple(self.active)

    async def claim(self, *args, **kwargs):
        return None

    async def next_retry(self, *, now):
        return None

    async def finish_pass(self, *, now):
        if self.active:
            self.pass_count += 1
        self.active.clear()

    async def snapshot(self, scan_id, *, now):
        return CollectionSnapshot(
            self.runs[scan_id],
            (),
            (),
            (),
            CollectionProgress(
                state="collecting" if scan_id in self.active else "partial",
                searches_pending=1,
                can_continue=True,
            ),
        )

    async def save(self, run):
        if run.status == "incomplete" and self.pass_count == 1:
            self.finished.set()
            await self.release.wait()
        self.runs[run.scan_id] = run
        if run.status == "incomplete" and self.pass_count == 2:
            self.second_finished.set()


class UnusedReader:
    async def retrieve(self, lead):
        raise AssertionError("This lifecycle scenario has no article work.")


@pytest.mark.parametrize("operation", ["continue", "start"])
async def test_request_during_final_projection_starts_the_next_worker(operation):
    journal = CheckpointJournal()
    service = ResumableDiscovery((), UnusedReader(), journal, clock=lambda: NOW)
    pending = None
    try:
        first = await service.start(1)
        await asyncio.wait_for(journal.finished.wait(), 1)
        pending = asyncio.create_task(
            service.continue_collection(first.scan_id)
            if operation == "continue"
            else service.start(1)
        )
        # Queue the request on the lifecycle lock before releasing final save.
        await asyncio.sleep(0)
        journal.release.set()
        accepted = await pending
        await asyncio.wait_for(journal.second_finished.wait(), 1)
        await service.wait(accepted.scan_id)
        assert (await service.get(accepted.scan_id)).status == "incomplete"
        assert not journal.active
        assert journal.pass_count == 2
        if operation == "continue":
            assert accepted.scan_id == first.scan_id
            assert accepted.interval == first.interval
    finally:
        journal.release.set()
        if pending is not None:
            await pending
        await service.aclose()


async def test_shutdown_waits_for_an_already_started_projection_write():
    writing = asyncio.Event()
    release_write = asyncio.Event()
    committed = asyncio.Event()

    class DurableJournal(CheckpointJournal):
        async def save(self, run):
            async def commit():
                writing.set()
                await release_write.wait()
                self.runs[run.scan_id] = run
                committed.set()

            # A transaction already running outside the event loop can commit
            # even when its caller is cancelled.
            await asyncio.shield(asyncio.create_task(commit()))

    journal = DurableJournal()
    service = ResumableDiscovery((), UnusedReader(), journal, clock=lambda: NOW)
    closing = None
    try:
        await service.start(1)
        await asyncio.wait_for(writing.wait(), 1)
        closing = asyncio.create_task(service.aclose())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(closing), 0.05)
        release_write.set()
        await asyncio.wait_for(closing, 1)
        assert committed.is_set()
    finally:
        release_write.set()
        if closing is not None:
            await closing
        await service.aclose()
