"""Stored HTTP reports keep earlier and later occurrence facts apart."""

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.domain.discovery import DiscoveryArticle, DiscoveryBatch
from disaster_monitor.domain.events import point_event_geometry
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)
from disaster_monitor.presentation.http.api import create_schema_app


@pytest.mark.parametrize("days", [1, 3, 7, 14, 30])
async def test_earlier_toll_cannot_acquire_current_article_time_place_or_point(
    tmp_path, days
):
    now = datetime(2026, 10, 14, tzinfo=UTC)
    source = SourceReference(
        "news",
        "Daily",
        "New flood in Brookside",
        "https://daily.example/report",
        now,
        None,
        now,
    )
    text = (
        "After a landslide killed three people last August, yesterday, "
        "11 October, another flood struck Brookside and killed two people."
    )
    geometry = point_event_geometry(10, 20, source)
    clock = datetime(2026, 10, 11, tzinfo=UTC)
    article = DiscoveryArticle(
        source, text, location="Brookside", geometry=geometry, event_time=clock
    )

    class Feed:
        source_id = "controlled"

        async def discover(self, *, interval):
            yield DiscoveryBatch(articles=(article,), successful_operations=1)

    store = FileDiscoveryStore(tmp_path)
    service = DiscoveryScanService((Feed(),), store, clock=lambda: now)
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(discovery_scans=service)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            started = await client.post(
                "/api/v1/discovery-scans", json={"reporting_days": days}
            )
            identifier = started.json()["scan_id"]
            await service.wait(identifier)
            result = (await client.get(f"/api/v1/discovery-scans/{identifier}")).json()
        incidents = result["snapshot"]["incidents"]
        assert len(incidents) == 2
        old = next(i for i in incidents if i["disaster"] == "landslide")
        new = next(i for i in incidents if i["disaster"] == "flood")
        assert old["geometry"] is None and old["event_time"] is None
        (old_report,) = old["discovery_reports"]
        assert old_report["location"] is None and old_report["geometry"] is None
        assert old_report["mention_role"] == "historical"
        assert old_report["event_time"] is None
        assert old_report["event_date_wording"] == "last August"
        assert old_report["source"]["canonical_url"] == source.canonical_url
        assert "last August" in old_report["mention_excerpt"]
        assert "11 October" not in old_report["mention_excerpt"]
        assert any(c["value"] == "three" for c in old_report["claims"])
        (new_report,) = new["discovery_reports"]
        assert new_report["location"] == "Brookside"
        assert new["event_time"].startswith("2026-10-11T")
        assert any(c["value"] == "two" for c in new_report["claims"])
        assert all(c["value"] != "three" for c in new_report["claims"])
        restored = await FileDiscoveryStore(tmp_path).read(identifier)
        assert restored.reports[0].article == article
    finally:
        await service.aclose()
