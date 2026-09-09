from datetime import timedelta

import pytest

from disaster_monitor.application.disaster import ProviderBatch
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsQuery,
    ActiveIncidentsService,
)
from disaster_monitor.application.ingestion.projection_jobs import (
    WorldwideIncidentProjectionScheduler,
)
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.disaster import Disaster, SourceAuthority, SourceReference
from disaster_monitor.domain.news import IncidentCandidate, IncidentCandidateStatus
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

from .active_incidents_support import (
    NOW,
    FakeWorldwideProvider,
    _event,
    _registration,
)


@pytest.mark.asyncio
async def test_durable_projection_is_read_without_provider_calls() -> None:
    provider = FakeWorldwideProvider(
        "projection-source",
        ProviderBatch(
            (
                _event(
                    "projection-source",
                    Disaster.EARTHQUAKE,
                    "quake-1",
                    NOW - timedelta(hours=1),
                ),
            )
        ),
    )
    repository = InMemoryOperationalRepository()
    writer = ActiveIncidentsService(
        ProviderRegistry(
            (_registration("Projection source", provider, Disaster.EARTHQUAKE),)
        ),
        country_catalog=StaticCountryCatalog(),
        clock=lambda: NOW,
        projection_store=repository,
    )

    written = await writer.refresh()

    reader = ActiveIncidentsService(
        ProviderRegistry(()),
        country_catalog=StaticCountryCatalog(),
        clock=lambda: NOW + timedelta(minutes=1),
        projection_store=repository,
        read_from_projection=True,
    )
    read = await reader.execute(ActiveIncidentsQuery(page_size=1))

    assert read.snapshot_version == written.snapshot_version
    assert [item.event_id for item in read.incidents] == ["quake-1"]
    assert len(provider.queries) == 1
    assert provider.queries[0][1] == NOW


@pytest.mark.asyncio
async def test_projection_scheduler_is_idempotent_and_worker_dispatches_it() -> None:
    repository = InMemoryOperationalRepository()
    scheduler = WorldwideIncidentProjectionScheduler(repository)

    assert await scheduler.enqueue_due(now=NOW) == 1
    assert await scheduler.enqueue_due(now=NOW + timedelta(seconds=30)) == 0

    calls = 0

    class ProjectionRefresher:
        async def refresh(self) -> object:
            nonlocal calls
            calls += 1
            return None

    class WatchRefresher:
        async def execute(self, watch_id: str) -> object:
            raise AssertionError(f"unexpected watch dispatch: {watch_id}")

    from disaster_monitor.application.ingestion.watch_jobs import IncidentWatchWorker

    job = await IncidentWatchWorker(
        repository,
        WatchRefresher(),
        projection_refresher=ProjectionRefresher(),
        clock=lambda: NOW,
    ).run_once("projection-worker")

    assert job is not None
    assert calls == 1
    assert repository.jobs[job.job_id].status.value == "succeeded"


@pytest.mark.asyncio
async def test_projection_publishes_news_candidate_with_complete_detection_clock() -> (
    None
):
    repository = InMemoryOperationalRepository()
    published = NOW - timedelta(hours=2)
    source = SourceReference(
        source_id="ap-news",
        publisher="Associated Press",
        title="Wildfire forces evacuations near Antalya, Turkey",
        canonical_url="https://apnews.com/article/antalya-fire",
        published_at=published,
        updated_at=None,
        retrieved_at=NOW - timedelta(minutes=10),
        authority=SourceAuthority.SECONDARY,
    )
    await repository.append_incident_candidate(
        IncidentCandidate(
            candidate_id="news-candidate:antalya",
            revision_id="news-candidate:antalya:1",
            disaster=Disaster.WILDFIRE,
            location="Antalya, Turkey",
            event_time=published,
            status=IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED,
            sources=(source,),
            news_break_at=published,
            first_observed_at=NOW - timedelta(minutes=10),
            candidate_created_at=NOW - timedelta(minutes=9),
        )
    )
    writer = ActiveIncidentsService(
        ProviderRegistry(()),
        country_catalog=StaticCountryCatalog(),
        clock=lambda: NOW,
        projection_store=repository,
        candidate_store=repository,
    )

    snapshot = await writer.refresh()

    incident = snapshot.incidents[0]
    assert incident.event_id == "news-candidate:antalya"
    assert (
        incident.verification_status
        is IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED
    )
    assert incident.detection.news_break_at == published
    assert incident.detection.first_observed_at == NOW - timedelta(minutes=10)
    assert incident.detection.candidate_created_at == NOW - timedelta(minutes=9)
    assert incident.detection.monitor_visible_at == NOW
    assert incident.detection.assistant_ready_at == NOW
    assert incident.detection.verified_at is None

    reader = ActiveIncidentsService(
        ProviderRegistry(()),
        country_catalog=StaticCountryCatalog(),
        projection_store=repository,
        read_from_projection=True,
    )
    restored = await reader.execute()
    assert restored.incidents[0].detection == incident.detection

    later_writer = ActiveIncidentsService(
        ProviderRegistry(()),
        country_catalog=StaticCountryCatalog(),
        clock=lambda: NOW + timedelta(minutes=5),
        projection_store=repository,
        candidate_store=repository,
    )
    refreshed = await later_writer.refresh()
    assert refreshed.incidents[0].detection.monitor_visible_at == NOW
    assert refreshed.incidents[0].detection.assistant_ready_at == NOW


@pytest.mark.asyncio
async def test_reconciliation_preserves_counts_and_detection_clocks() -> None:
    repository = InMemoryOperationalRepository()
    published = NOW - timedelta(hours=2)
    source = SourceReference(
        source_id="ap-news",
        publisher="Associated Press",
        title="Wildfire forces evacuations near Antalya, Turkey",
        canonical_url="https://apnews.com/article/antalya-fire",
        published_at=published,
        updated_at=None,
        retrieved_at=NOW - timedelta(minutes=10),
        authority=SourceAuthority.SECONDARY,
    )
    await repository.append_incident_candidate(
        IncidentCandidate(
            candidate_id="news-candidate:antalya",
            revision_id="news-candidate:antalya:1",
            disaster=Disaster.WILDFIRE,
            location="Antalya, Turkey",
            event_time=published,
            status=IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED,
            sources=(source,),
            news_break_at=published,
            first_observed_at=NOW - timedelta(minutes=10),
            candidate_created_at=NOW - timedelta(minutes=9),
        )
    )
    provider = FakeWorldwideProvider(
        "authoritative-source",
        ProviderBatch(
            (
                _event(
                    "authoritative-source",
                    Disaster.WILDFIRE,
                    "wildfire-1",
                    published,
                    location="Antalya, Turkey",
                ),
            )
        ),
    )

    async def refresh(at):
        return await ActiveIncidentsService(
            ProviderRegistry(
                (_registration("Authoritative source", provider, Disaster.WILDFIRE),)
            ),
            country_catalog=StaticCountryCatalog(),
            clock=lambda: at,
            projection_store=repository,
            candidate_store=repository,
        ).refresh()

    first = await refresh(NOW)
    second = await refresh(NOW + timedelta(minutes=5))

    assert len(first.incidents) == 1
    assert (
        next(
            item for item in first.coverage if item.disaster is Disaster.WILDFIRE
        ).incident_count
        == 1
    )
    assert first.incidents[0].detection.verified_at == NOW
    assert second.incidents[0].detection.verified_at == NOW
    assert second.incidents[0].detection.monitor_visible_at == NOW
    assert second.incidents[0].detection.assistant_ready_at == NOW
