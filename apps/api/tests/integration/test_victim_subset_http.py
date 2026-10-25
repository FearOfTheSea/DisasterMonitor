"""HTTP projection preserves domain scope decisions and retained article context."""

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
async def test_raw_location_cannot_override_unallocated_toll_in_a_stored_scan(
    tmp_path, days
):
    now = datetime(2026, 10, 25, tzinfo=UTC)
    source = SourceReference(
        "news",
        "Daily",
        "Floods in Brookside",
        "https://daily.example/report",
        now,
        None,
        now,
    )
    text = "Two people died in floods, one of them a worker in Brookside."
    geometry = point_event_geometry(10, 20, source)
    article = DiscoveryArticle(source, text, location="Brookside", geometry=geometry)

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
        assert result["unlocated_count"] == 1
        (incident,) = result["snapshot"]["incidents"]
        assert incident["geometry"] is None
        assert incident["location"] != "Brookside"
        (report,) = incident["discovery_reports"]
        assert report["location"] is None
        assert report["location_precision"] == "unresolved"
        assert report["geometry"] is None
        assert report["source"]["canonical_url"] == source.canonical_url
        assert any(
            c["value"] == "Two" and c["excerpt"] == text for c in report["claims"]
        )
        restored = await FileDiscoveryStore(tmp_path).read(identifier)
        assert restored.reports[0].article.location == "Brookside"
        assert restored.reports[0].article.geometry == geometry
    finally:
        await service.aclose()
