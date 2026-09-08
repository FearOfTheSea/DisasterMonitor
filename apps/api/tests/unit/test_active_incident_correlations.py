from datetime import timedelta

import pytest

from disaster_monitor.application.disaster import ProviderBatch
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.disaster import Disaster

from .active_incidents_support import (
    NOW,
    FakeWorldwideProvider,
    _active_incidents_service,
    _event,
    _registration,
)


@pytest.mark.asyncio
async def test_active_incidents_correlate_only_retained_cross_hazard_records() -> None:
    earthquake = FakeWorldwideProvider(
        "earthquakes",
        ProviderBatch(
            (
                _event(
                    "earthquakes",
                    Disaster.EARTHQUAKE,
                    "quake",
                    NOW - timedelta(hours=2),
                ),
            )
        ),
    )
    landslide = FakeWorldwideProvider(
        "landslides",
        ProviderBatch(
            (
                _event(
                    "landslides",
                    Disaster.LANDSLIDE,
                    "slide",
                    NOW,
                    longitude=133.7,
                ),
            )
        ),
    )
    service = _active_incidents_service(
        ProviderRegistry(
            (
                _registration("Earthquakes", earthquake, Disaster.EARTHQUAKE),
                _registration("Landslides", landslide, Disaster.LANDSLIDE),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert len(snapshot.correlations) == 1
    assert snapshot.correlations[0].first_event_id == "quake"
    assert snapshot.correlations[0].second_event_id == "slide"
    assert snapshot.correlations[0].source_ids == ("earthquakes", "landslides")
