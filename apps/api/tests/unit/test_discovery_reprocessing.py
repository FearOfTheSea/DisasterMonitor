"""Reassessment preserves original acquisition and never requests news again."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)

NOW = datetime(2026, 10, 19, tzinfo=UTC)


@pytest.mark.asyncio
async def test_reprocess_preserves_original_and_reassesses_retained_articles_only(
    tmp_path,
):
    source = SourceReference(
        "news", "Daily", "Flood response", "https://news.example/report", NOW, None, NOW
    )
    article = DiscoveryArticle(
        source, "Floods hit Riverton on Aug. 26. Two people died."
    )
    interval = ReportingInterval.at_start(30, NOW)
    old_report = replace(assess_article(article, interval), mentions=())
    original = DiscoveryRun(
        "11111111-1111-4111-8111-111111111111",
        interval,
        status="incomplete",
        reports=(old_report,),
        successful_operations=2,
        failed_operations=1,
        truncated=True,
        issues=("Original provider cap",),
        finished_at=NOW,
    )
    store = FileDiscoveryStore(tmp_path)
    await store.save(original)

    class NeverAcquire:
        source_id = "must-not-run"

        async def discover(self, *, interval):
            raise AssertionError("Reprocessing must not reacquire news")
            yield

    service = DiscoveryScanService((NeverAcquire(),), store, clock=lambda: NOW)
    try:
        pending = await service.reprocess(original.scan_id)
        assert pending.status == "running"
        await service.wait(pending.scan_id)
        result = await service.get(pending.scan_id)
        assert result.scan_id != original.scan_id
        assert result.reprocessed_from == original.scan_id
        assert result.interval == interval
        assert result.status == "incomplete"
        assert result.truncated and result.failed_operations == 1
        assert result.reports[0].article == article
        assert result.events[0].event_time == datetime(2026, 8, 26, tzinfo=UTC)
        assert await store.read(original.scan_id) == original
        assert await store.read(result.scan_id) == result
        assert any("no new news acquisition" in issue for issue in result.issues)
        next_pending = await service.reprocess(result.scan_id)
        await service.wait(next_pending.scan_id)
        again = await service.get(next_pending.scan_id)
        assert again.reprocessed_from == original.scan_id
        assert again.reports == result.reports
        assert {e.event_id for e in again.events}.isdisjoint(
            e.event_id for e in result.events
        )
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_derived_result_retention_keeps_its_original_acquisition(tmp_path):
    store = FileDiscoveryStore(tmp_path)
    interval = ReportingInterval.at_start(7, NOW)
    original = DiscoveryRun(
        "11111111-1111-4111-8111-111111111111",
        interval,
        status="completed",
        finished_at=NOW,
    )
    await store.save(original)
    for index in range(8):
        await store.save(
            replace(
                original,
                scan_id=f"22222222-2222-4222-8222-{index:012}",
                reprocessed_from=original.scan_id,
            )
        )
    assert await store.read(original.scan_id) == original


@pytest.mark.asyncio
async def test_running_or_missing_scans_cannot_be_reprocessed(tmp_path):
    store = FileDiscoveryStore(tmp_path)
    original = DiscoveryRun(
        "11111111-1111-4111-8111-111111111111", ReportingInterval.at_start(7, NOW)
    )
    await store.save(original)
    service = DiscoveryScanService((), store)
    with pytest.raises(ValueError):
        await service.reprocess(original.scan_id)
    with pytest.raises(LookupError):
        await service.reprocess("22222222-2222-4222-8222-222222222222")
