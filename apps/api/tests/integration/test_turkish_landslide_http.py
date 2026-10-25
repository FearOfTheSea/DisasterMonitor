"""Typed Turkish fatality reporting stays accessible through stored scan HTTP."""

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.domain.discovery import DiscoveryArticle, DiscoveryBatch
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)
from disaster_monitor.presentation.http.api import create_schema_app


@pytest.mark.parametrize("days", [1, 3, 7, 14, 30])
async def test_turkish_landslide_fatality_survives_persistence_and_http(tmp_path, days):
    now = datetime(2026, 10, 25, tzinfo=UTC)
    source = SourceReference(
        "news",
        "Daily",
        "Heyelanda bir kişi hayatını kaybetti",
        "https://daily.example/report",
        now,
        None,
        now,
    )
    text = "Heyelan sonucu bir kişi hayatını kaybetti."
    article = DiscoveryArticle(source, text)

    class Feed:
        source_id = "controlled"

        async def discover(self, *, interval):
            yield DiscoveryBatch(articles=(article,), successful_operations=1)

    service = DiscoveryScanService(
        (Feed(),), FileDiscoveryStore(tmp_path), clock=lambda: now
    )
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
        (incident,) = result["snapshot"]["incidents"]
        assert incident["disaster"] == "landslide"
        assert incident["event_time"] is None and incident["geometry"] is None
        assert incident["identity_status"] == "candidate"
        (report,) = incident["discovery_reports"]
        assert report["source"]["canonical_url"] == source.canonical_url
        assert report["location"] is None and report["event_time"] is None
        assert any(
            c["category"] == "fatalities" and c["value"] == "1" and c["excerpt"] == text
            for c in report["claims"]
        )
        restored = await FileDiscoveryStore(tmp_path).read(identifier)
        assert restored.reports[0].article == article
    finally:
        await service.aclose()
