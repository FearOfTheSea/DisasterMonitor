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
from disaster_monitor.domain.disaster import Disaster
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
