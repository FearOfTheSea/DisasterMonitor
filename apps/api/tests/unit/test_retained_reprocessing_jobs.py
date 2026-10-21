"""Retained assessment returns a saved job before expensive source processing."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event

import pytest

from disaster_monitor.application.incidents.discovery_reprocessing import (
    reprocess_retained_run,
)
from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval

NOW = datetime(2026, 10, 16, tzinfo=UTC)


class MemoryStore:
    def __init__(self):
        self.runs = {}

    async def save(self, run):
        self.runs[run.scan_id] = run

    async def read(self, scan_id):
        return self.runs.get(scan_id)

    async def recent(self):
        return tuple(self.runs.values())


async def test_reassessment_acknowledges_saved_job_before_processing_and_shares_it(
    monkeypatch,
):
    entered, release = Event(), Event()
    calls = []

    def delayed(original, **kwargs):
        calls.append(original.scan_id)
        entered.set()
        assert release.wait(5)
        return reprocess_retained_run(original, **kwargs)

    monkeypatch.setattr(
        "disaster_monitor.application.incidents.discovery_scan.reprocess_retained_run",
        delayed,
    )
    store = MemoryStore()
    original = DiscoveryRun(
        "original",
        ReportingInterval.at_start(7, NOW),
        status="completed",
        finished_at=NOW,
        successful_operations=1,
    )
    await store.save(original)
    service = DiscoveryScanService((), store, clock=lambda: NOW)
    request = asyncio.create_task(service.reprocess(original.scan_id))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        try:
            pending = await asyncio.wait_for(asyncio.shield(request), 0.5)
        except TimeoutError:
            pytest.fail(
                "Reprocessing waited for source assessment before acknowledging"
            )
        assert pending.status == "running"
        assert pending.reprocessed_from == original.scan_id
        assert await store.read(pending.scan_id) == pending
        shared = await service.reprocess(original.scan_id)
        assert shared.scan_id == pending.scan_id
        assert await store.read(original.scan_id) == original
        release.set()
        await service.wait(pending.scan_id)
        result = await service.get(pending.scan_id)
        assert result.status == "completed"
        assert result.interval == original.interval
        assert calls == [original.scan_id]
    finally:
        release.set()
        await asyncio.gather(request, return_exceptions=True)
        await service.aclose()


async def test_opening_saved_reassessment_after_restart_resumes_same_job():
    store = MemoryStore()
    original = DiscoveryRun(
        "original",
        ReportingInterval.at_start(7, NOW),
        status="completed",
        finished_at=NOW,
        successful_operations=1,
    )
    pending = replace(
        original,
        scan_id="pending",
        reprocessed_from="original",
        status="running",
        finished_at=None,
    )
    await store.save(original)
    await store.save(pending)
    restarted = DiscoveryScanService((), store, clock=lambda: NOW)
    try:
        await restarted.get(pending.scan_id)
        await restarted.wait(pending.scan_id)
        result = await restarted.get(pending.scan_id)
        assert result.status == "completed"
        assert result.scan_id == pending.scan_id
        assert result.reprocessed_from == original.scan_id
        assert await store.read(original.scan_id) == original
    finally:
        await restarted.aclose()


async def test_assessment_failure_stops_polling_without_losing_previous_results(
    monkeypatch,
):
    calls = []

    def failed(original, **kwargs):
        calls.append(original.scan_id)
        raise ValueError("controlled assessment failure")

    monkeypatch.setattr(
        "disaster_monitor.application.incidents.discovery_scan.reprocess_retained_run",
        failed,
    )
    store = MemoryStore()
    original = DiscoveryRun(
        "original",
        ReportingInterval.at_start(7, NOW),
        status="completed",
        finished_at=NOW,
        successful_operations=1,
    )
    await store.save(original)
    service = DiscoveryScanService((), store, clock=lambda: NOW)
    try:
        pending = await service.reprocess(original.scan_id)
        await service.wait(pending.scan_id)
        result = await service.get(pending.scan_id)
        assert result.status == "incomplete"
        assert any("reassessment failed" in issue for issue in result.issues)
        assert result.reports == original.reports
        assert result.events == original.events
        assert await store.read(original.scan_id) == original
        await service.get(pending.scan_id)
        assert calls == [original.scan_id]
    finally:
        await service.aclose()


async def test_reassessment_storage_failure_is_visible_without_a_running_job():
    class RefusedStore(MemoryStore):
        async def save(self, run):
            if run.reprocessed_from and run.status != "running":
                raise OSError("controlled storage failure")
            await super().save(run)

    store = RefusedStore()
    original = DiscoveryRun(
        "original",
        ReportingInterval.at_start(7, NOW),
        status="completed",
        finished_at=NOW,
        successful_operations=1,
    )
    await store.save(original)
    service = DiscoveryScanService((), store, clock=lambda: NOW)
    try:
        pending = await service.reprocess(original.scan_id)
        await service.wait(pending.scan_id)
        result = await service.get(pending.scan_id)
        assert result.status == "incomplete"
        assert any("this process only" in issue for issue in result.issues)
        assert await store.read(original.scan_id) == original
    finally:
        await service.aclose()


async def test_shutdown_drains_an_accepted_result_write_before_returning():
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class DelayedStore(MemoryStore):
        async def save(self, run):
            if run.reprocessed_from and run.status != "running":
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            await super().save(run)

    store = DelayedStore()
    original = DiscoveryRun(
        "original",
        ReportingInterval.at_start(7, NOW),
        status="completed",
        finished_at=NOW,
        successful_operations=1,
    )
    await store.save(original)
    service = DiscoveryScanService((), store, clock=lambda: NOW)
    closing = None
    try:
        pending = await service.reprocess(original.scan_id)
        await asyncio.wait_for(entered.wait(), 2)
        closing = asyncio.create_task(service.aclose())
        done, _ = await asyncio.wait((closing,), timeout=0.05)
        assert not done, "Shutdown returned while a result write was still pending"
        assert not cancelled.is_set()
        release.set()
        await closing
        assert (await store.read(pending.scan_id)).status == "completed"
    finally:
        release.set()
        if closing:
            await closing
        else:
            await service.aclose()


async def test_ten_users_can_queue_distinct_reassessments_with_one_worker(monkeypatch):
    entered, release = Event(), Event()
    calls = []

    def delayed(original, **kwargs):
        calls.append(original.scan_id)
        entered.set()
        assert release.wait(5)
        return reprocess_retained_run(original, **kwargs)

    monkeypatch.setattr(
        "disaster_monitor.application.incidents.discovery_scan.reprocess_retained_run",
        delayed,
    )
    store = MemoryStore()
    originals = [
        DiscoveryRun(
            f"original-{index}",
            ReportingInterval.at_start(7, NOW),
            status="completed",
            finished_at=NOW,
            successful_operations=1,
        )
        for index in range(11)
    ]
    for original in originals:
        await store.save(original)
    service = DiscoveryScanService((), store, clock=lambda: NOW)
    try:
        pending = await asyncio.gather(
            *(service.reprocess(original.scan_id) for original in originals[:10]),
            return_exceptions=True,
        )
        assert all(isinstance(run, DiscoveryRun) for run in pending)
        assert len({run.scan_id for run in pending}) == 10
        assert await asyncio.to_thread(entered.wait, 2)
        assert len(calls) == 1  # CPU assessment stays bounded while users queue.
        with pytest.raises(ValueError, match="running"):
            await service.reprocess(originals[-1].scan_id)
        release.set()
        await asyncio.gather(*(service.wait(run.scan_id) for run in pending))
        assert len(calls) == 10
        for original, run in zip(originals, pending, strict=False):
            assert (await service.get(run.scan_id)).status == "completed"
            assert await store.read(original.scan_id) == original
    finally:
        release.set()
        await service.aclose()
