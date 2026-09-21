from datetime import timedelta

import pytest

from disaster_monitor.application.disaster import (
    ObservationKind,
    ProviderBatch,
    WorldwideDisasterEvent,
)
from disaster_monitor.application.incidents.active_incidents import (
    IncidentCoverageState,
)
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.disaster import (
    Disaster,
    EventTimePrecision,
    ProviderTier,
    point_event_geometry,
)
from disaster_monitor.domain.operations import ProviderAttemptOutcome
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

from .active_incidents_support import (
    NOW,
    FakeWorldwideProvider,
    _active_incidents_service,
    _coverage,
    _registration,
    _source,
)


@pytest.mark.asyncio
async def test_week_precision_events_are_preliminary_observations_not_incidents() -> (
    None
):
    week_start = NOW.replace(hour=0) - timedelta(days=6)
    week_end = NOW.replace(hour=0)
    source = _source("smithsonian", week_start)
    provider = FakeWorldwideProvider(
        "smithsonian",
        ProviderBatch(
            (
                WorldwideDisasterEvent(
                    event_id="wvar-eruptive-activity:262000:20260814",
                    disaster=Disaster.VOLCANIC_ERUPTION,
                    location="Suwanosejima, Ryukyu Volcanic Arc",
                    event_time=week_start,
                    event_time_end=week_end,
                    event_time_precision=EventTimePrecision.WEEK,
                    source=source,
                    geometry=point_event_geometry(29.638, 129.714, source),
                    observation_kind=ObservationKind.PRELIMINARY_EVENT,
                ),
            )
        ),
    )
    repository = InMemoryOperationalRepository()
    service = _active_incidents_service(
        ProviderRegistry(
            (
                _registration(
                    "Smithsonian WVAR",
                    provider,
                    Disaster.VOLCANIC_ERUPTION,
                    tier=ProviderTier.PRIMARY,
                ),
            )
        ),
        clock=lambda: NOW,
        projection_store=repository,
        provider_attempt_recorder=repository,
    )

    snapshot = await service.execute()

    assert snapshot.incidents == ()
    assert len(snapshot.observations) == 1
    observation = snapshot.observations[0]
    assert observation.observation_kind is ObservationKind.PRELIMINARY_EVENT
    assert observation.event_time_precision is EventTimePrecision.WEEK
    assert observation.event_time_end == week_end
    coverage = _coverage(snapshot)[Disaster.VOLCANIC_ERUPTION]
    assert coverage.state is IncidentCoverageState.NO_MATCHING_RECORDS
    assert coverage.scan_complete is True
    assert snapshot.warnings == ()
    attempts = await repository.provider_attempts(source_id="smithsonian", limit=1)
    assert attempts[0].outcome is ProviderAttemptOutcome.SUCCESS

    restored = await _active_incidents_service(
        ProviderRegistry(()),
        clock=lambda: NOW,
        projection_store=repository,
        read_from_projection=True,
    ).execute()
    assert restored.observations == snapshot.observations


def test_week_precision_cannot_be_promoted_to_a_physical_event() -> None:
    week_start = NOW.replace(hour=0) - timedelta(days=6)
    with pytest.raises(ValueError, match="preliminary observation"):
        WorldwideDisasterEvent(
            event_id="invalid-week-event",
            disaster=Disaster.VOLCANIC_ERUPTION,
            location="Fixture volcano",
            event_time=week_start,
            event_time_end=NOW.replace(hour=0),
            event_time_precision=EventTimePrecision.WEEK,
            source=_source("smithsonian", NOW),
        )
