"""Stored HTTP reporting retains comparisons without borrowing their tolls."""

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
async def test_recalled_landslide_does_not_borrow_current_earthquake_deaths(
    tmp_path, days
):
    now = datetime(2026, 10, 25, tzinfo=UTC)
    source = SourceReference(
        "news",
        "Daily",
        "Terremoto y recuperación",
        "https://daily.example/report",
        now,
        None,
        now,
    )
    comparison = (
        "Me dijeron que son muchos fallecidos y que me acuerde de los deslaves "
        "ocurridos en 1999, cuando todavía buscan a los desaparecidos."
    )
    text = "El terremoto mató a cinco personas. " + comparison
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
        reports = [
            (incident["disaster"], report)
            for incident in result["snapshot"]["incidents"]
            for report in incident["discovery_reports"]
        ]
        assert any(
            hazard == "earthquake"
            and any(
                c["category"] == "fatalities" and c["value"] == "5"
                for c in report["claims"]
            )
            for hazard, report in reports
        )
        landslides = [r for h, r in reports if h == "landslide"]
        assert landslides
        for report in landslides:
            assert report["mention_excerpt"] == comparison
            assert report["source"]["canonical_url"] == source.canonical_url
            assert not [c for c in report["claims"] if c["category"] == "fatalities"]
        restored = await FileDiscoveryStore(tmp_path).read(identifier)
        assert restored.reports[0].article == article
    finally:
        await service.aclose()
