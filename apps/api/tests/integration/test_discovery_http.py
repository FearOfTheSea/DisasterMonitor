import asyncio
from dataclasses import replace
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


async def test_multitopic_report_only_projects_hazard_linked_impact_sentences(tmp_path):
    class Feed:
        source_id = "fixture"

        async def discover(self, *, interval):
            yield DiscoveryBatch(
                articles=(
                    DiscoveryArticle(
                        source=SourceReference(
                            "open-news",
                            "Humanitarian source",
                            "Country humanitarian snapshot",
                            "https://fixture.example/snapshot",
                            NOW,
                            None,
                            NOW,
                        ),
                        text=(
                            "Drought displaced 200 people. "
                            "Violence killed dozens of people. "
                            "Cholera caused 17 deaths."
                        ),
                    ),
                ),
                successful_operations=1,
            )

    store = FileDiscoveryStore(tmp_path)
    service = DiscoveryScanService((Feed(),), store, clock=lambda: NOW)
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(discovery_scans=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = await client.post(
            "/api/v1/discovery-scans", json={"reporting_days": 7}
        )
        identifier = started.json()["scan_id"]
        await service.wait(identifier)
        # A scan retained before the scope fix can contain obsolete extracted
        # fatality excerpts. Current projection must not revive those claims.
        run = await service.get(identifier)
        legacy_report = replace(
            run.reports[0], fatality_evidence=("Cholera caused 17 deaths.",)
        )
        await store.save(
            replace(
                run,
                reports=(legacy_report,),
                events=(replace(run.events[0], reports=(legacy_report,)),),
            )
        )
        result = (await client.get(f"/api/v1/discovery-scans/{identifier}")).json()
    report = result["snapshot"]["incidents"][0]["discovery_reports"][0]
    assert report["fatality_evidence"] == []
    assert [(claim["category"], claim["value"]) for claim in report["claims"]] == [
        ("displacement", "200")
    ]
    await service.aclose()


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
