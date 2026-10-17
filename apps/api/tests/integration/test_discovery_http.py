import asyncio
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

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_http_scan_retains_unlocated_reports_and_fixed_publication_window(
    tmp_path,
):
    gate = asyncio.Event()

    class Feed:
        source_id = "fixture"

        async def discover(self, *, interval):
            await gate.wait()
            yield DiscoveryBatch(
                articles=(
                    DiscoveryArticle(
                        source=SourceReference(
                            "open-news",
                            "Fixture international news",
                            "Drought in Test Province",
                            "https://fixture.example/drought",
                            NOW,
                            None,
                            NOW,
                        ),
                        text="Officials report two people died.",
                        indexed_at=NOW,
                    ),
                ),
                successful_operations=1,
            )

    service = DiscoveryScanService(
        (Feed(),), FileDiscoveryStore(tmp_path), clock=lambda: NOW
    )
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(discovery_scans=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for days in (1, 3, 7, 14, 30):
            response = await client.post(
                "/api/v1/discovery-scans", json={"reporting_days": days}
            )
            assert response.status_code == 202
            assert response.json()["status"] == "running"
            assert response.json()["reporting_days"] == days
        assert (
            await client.post("/api/v1/discovery-scans", json={"reporting_days": 2})
        ).status_code == 422
        gate.set()
        await service.wait(response.json()["scan_id"])
        result = (
            await client.get(f"/api/v1/discovery-scans/{response.json()['scan_id']}")
        ).json()
        assert result["status"] == "completed"
        assert result["interval_end"] == "2026-10-17T12:00:00Z"
        assert result["unlocated_count"] == 1
        incident = result["snapshot"]["incidents"][0]
        assert incident["geometry"] is None
        assert incident["event_time"] is None
        assert incident["event_time_basis"] == "unknown"
        assert incident["verification_status"] == "provisional_news_detected"
        assert incident["discovery_reports"][0]["event_time"] is None
        assert incident["discovery_reports"][0]["fatality_evidence"]
    await service.aclose()
