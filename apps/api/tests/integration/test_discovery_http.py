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


async def test_continue_http_retains_exact_interval_and_exposes_durable_progress(
    tmp_path,
):
    from disaster_monitor.application.incidents.resumable_discovery import (
        ResumableDiscovery,
    )
    from disaster_monitor.domain.collection import CollectionPage
    from disaster_monitor.infrastructure.operations.sqlite_collection import (
        SQLiteCollectionJournal,
    )

    class Provider:
        source_id = "controlled"
        queries = ("flood",)
        supports_alternates = False

        async def fetch_page(self, partition):
            return CollectionPage(next_cursor="next" if not partition.cursor else None)

    class Reader:
        async def retrieve(self, lead):
            raise AssertionError("No lead retrieval expected")

    journal = SQLiteCollectionJournal(tmp_path / "jobs.sqlite")
    runtime = ResumableDiscovery(
        (Provider(),), Reader(), journal, clock=lambda: NOW, page_budget=1
    )
    service = DiscoveryScanService((), journal, collection=runtime)
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(discovery_scans=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = await client.post(
            "/api/v1/discovery-scans", json={"reporting_days": 1}
        )
        assert started.status_code == 202
        body = started.json()
        await service.wait(body["scan_id"])
        before = (await client.get(f"/api/v1/discovery-scans/{body['scan_id']}")).json()
        assert before["collection"]["can_continue"]
        continued = await client.post(
            f"/api/v1/discovery-scans/{body['scan_id']}/continue"
        )
        assert continued.status_code == 202
        assert continued.json()["interval_start"] == body["interval_start"]
        assert continued.json()["interval_end"] == body["interval_end"]
        await service.wait(body["scan_id"])
        after = (await client.get(f"/api/v1/discovery-scans/{body['scan_id']}")).json()
        assert after["status"] == "completed"
        assert after["collection"]["pages_acquired"] == 2
    await service.aclose()


async def test_http_reprocessing_preserves_window_and_exposes_original_provenance(
    tmp_path,
):
    class Feed:
        source_id = "fixture"
        calls = 0

        async def discover(self, *, interval):
            self.calls += 1
            yield DiscoveryBatch(
                articles=(
                    DiscoveryArticle(
                        SourceReference(
                            "news",
                            "Daily",
                            "Flood response",
                            "https://fixture.example/report",
                            NOW,
                            None,
                            NOW,
                        ),
                        "Floods hit Riverton on Aug. 26. Two people died.",
                    ),
                ),
                successful_operations=1,
            )

    feed = Feed()
    service = DiscoveryScanService(
        (feed,), FileDiscoveryStore(tmp_path), clock=lambda: NOW
    )
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(discovery_scans=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        started = (
            await client.post("/api/v1/discovery-scans", json={"reporting_days": 30})
        ).json()
        await service.wait(started["scan_id"])
        replay = await client.post(
            f"/api/v1/discovery-scans/{started['scan_id']}/reprocess"
        )
        assert replay.status_code == 200
        result = replay.json()
        assert result["reprocessed_from"] == started["scan_id"]
        assert result["interval_start"] == started["interval_start"]
        assert result["interval_end"] == started["interval_end"]
        assert result["scan_id"] != started["scan_id"]
        assert result["snapshot"]["incidents"][0]["event_time"].startswith("2026-08-26")
        assert feed.calls == 1
    await service.aclose()


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
