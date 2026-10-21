"""Pending retained assessments recover through the normal SQLite/runtime boundary."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 16, tzinfo=UTC)


class NoArticleReader:
    async def retrieve(self, lead):
        raise AssertionError("Retained reassessment must not acquire articles")


async def test_saved_reassessment_recovers_same_identity_without_acquisition(tmp_path):
    path = tmp_path / "jobs.sqlite"
    store = SQLiteCollectionJournal(path)
    original = DiscoveryRun(
        str(uuid4()),
        ReportingInterval.at_start(30, NOW),
        status="completed",
        finished_at=NOW,
        successful_operations=1,
    )
    pending = replace(
        original,
        scan_id=str(uuid4()),
        status="running",
        finished_at=None,
        reprocessed_from=original.scan_id,
    )
    await store.save(original)
    await store.save(pending)
    reopened = SQLiteCollectionJournal(path)
    runtime = ResumableDiscovery((), NoArticleReader(), reopened, clock=lambda: NOW)
    service = DiscoveryScanService(
        (),
        reopened,
        collection=runtime,
        clock=lambda: NOW,
    )
    try:
        await service.recover()
        assert not await reopened.active_scans()
        await service.get(pending.scan_id)
        await service.wait(pending.scan_id)
        result = await service.get(pending.scan_id)
        assert result.status == "completed"
        assert result.scan_id == pending.scan_id
        assert result.interval == original.interval
        assert result.reprocessed_from == original.scan_id
        assert await reopened.read(original.scan_id) == original
        assert not await reopened.active_scans()
    finally:
        await service.aclose()
