from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import FakeLanguageModel

from disaster_monitor.application.use_cases.refresh_incident_watch import (
    RefreshIncidentWatch,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    IncidentWatch,
    IncidentWatchObservation,
    ProviderTier,
    SourceAuthority,
    SourceReference,
    WatchCoverageState,
    WatchIncident,
    point_event_geometry,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)
from disaster_monitor.main import create_app

NOW = datetime(2026, 8, 31, 8, tzinfo=UTC)


def observed_incident() -> WatchIncident:
    source = SourceReference(
        "fixture-watch-source",
        "Fixture Authority",
        "Fixture flood event",
        "https://fixture-watch-source.example/events/flood-1",
        NOW,
        NOW,
        NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    return WatchIncident.from_source_evidence(
        event_id="flood-1",
        disaster=Disaster.FLOOD,
        location="Fixture delta",
        event_time=NOW,
        geometry=point_event_geometry(10.5, 106.5, source),
        measurements=(),
        provider_ids=("fixture:flood-1",),
        provider_tier=ProviderTier.PRIMARY,
        source_authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
        source=source,
        evidence_sources=(source,),
    )


@pytest.mark.asyncio
async def test_incident_watch_crud_timeline_and_read_contract(tmp_path: Path) -> None:
    repository = InMemoryOperationalRepository()
    app = create_app(
        settings=Settings(
            operational_blob_root=tmp_path / "blobs",
            country_catalog_root=tmp_path / "countries",
            country_catalog_automatic_updates=False,
        ),
        model=FakeLanguageModel(),
        operational_repository=repository,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/incident-watches",
            json={
                "disaster": "flood",
                "scope": {"kind": "country", "country": "vietnam"},
                "refresh_interval_seconds": 900,
            },
        )
        assert created.status_code == 201
        watch_id = created.json()["watch_id"]
        assert created.json()["scope"] == {
            "kind": "country",
            "country_code": "VNM",
            "country_name": "Vietnam",
        }
        assert created.json()["unread_change_count"] == 0

        class Discovery:
            async def observe_watch(self, selected_watch: IncidentWatch):
                return IncidentWatchObservation.create(
                    watch_id=selected_watch.watch_id,
                    observed_at=NOW,
                    coverage_state=WatchCoverageState.EVENTS_FOUND,
                    incidents=(observed_incident(),),
                    provider_names=("Fixture provider",),
                    warnings=(),
                    successful=True,
                )

        await RefreshIncidentWatch(repository, Discovery()).execute(watch_id)

        listed = await client.get("/api/v1/incident-watches")
        timeline = await client.get(f"/api/v1/incident-watches/{watch_id}/timeline")
        disabled = await client.post(
            f"/api/v1/incident-watches/{watch_id}/enabled",
            json={"enabled": False},
        )
        marked_read = await client.post(
            f"/api/v1/incident-watches/{watch_id}/timeline/read",
            json={"change_ids": [timeline.json()[0]["change_id"]]},
        )
        deleted = await client.delete(f"/api/v1/incident-watches/{watch_id}")
        missing = await client.get(f"/api/v1/incident-watches/{watch_id}/timeline")

    assert listed.status_code == 200
    assert listed.json()[0]["coverage_state"] == "events_found"
    assert listed.json()[0]["unread_change_count"] == 1
    assert timeline.status_code == 200
    assert timeline.json()[0]["kind"] == "new_event"
    assert timeline.json()[0]["source_ids"] == ["fixture-watch-source"]
    assert timeline.json()[0]["incident"]["geometry"]["coordinates"] == [
        {"latitude": 10.5, "longitude": 106.5}
    ]
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    assert marked_read.status_code == 200
    assert marked_read.json()["unread_change_count"] == 0
    assert deleted.status_code == 204
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_incident_watch_http_validation_preserves_scope_rules(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(
            operational_blob_root=tmp_path / "blobs",
            country_catalog_root=tmp_path / "countries",
            country_catalog_automatic_updates=False,
        ),
        model=FakeLanguageModel(),
        operational_repository=InMemoryOperationalRepository(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        invalid_country = await client.post(
            "/api/v1/incident-watches",
            json={
                "disaster": "earthquake",
                "scope": {"kind": "country", "country": "Atlantis"},
                "refresh_interval_seconds": 900,
            },
        )
        invalid_worldwide = await client.post(
            "/api/v1/incident-watches",
            json={
                "disaster": "earthquake",
                "scope": {"kind": "worldwide", "country": "Japan"},
                "refresh_interval_seconds": 900,
            },
        )
        invalid_interval = await client.post(
            "/api/v1/incident-watches",
            json={
                "disaster": "earthquake",
                "scope": {"kind": "worldwide"},
                "refresh_interval_seconds": 60,
            },
        )

    assert invalid_country.status_code == 422
    assert invalid_worldwide.status_code == 422
    assert invalid_interval.status_code == 422
