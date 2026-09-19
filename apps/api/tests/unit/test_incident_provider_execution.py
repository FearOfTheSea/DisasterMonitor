import asyncio

import pytest

from disaster_monitor.application.disaster import ProviderBatch
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.operations import ProviderAttempt, ProviderAttemptOutcome

from .active_incidents_support import (
    NOW,
    FakeWorldwideProvider,
    _active_incidents_service,
    _event,
    _registration,
)


@pytest.mark.asyncio
async def test_queries_independent_worldwide_providers_concurrently() -> None:
    started: set[str] = set()
    both_started = asyncio.Event()

    class CoordinatedProvider(FakeWorldwideProvider):
        async def find_worldwide_events(self, query, *, now):
            started.add(self.source_id)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1.0)
            return await super().find_worldwide_events(query, now=now)

    first = CoordinatedProvider(
        "first-earthquakes",
        ProviderBatch(
            (_event("first-earthquakes", Disaster.EARTHQUAKE, "first", NOW),)
        ),
    )
    second = CoordinatedProvider(
        "second-earthquakes",
        ProviderBatch(
            (
                _event(
                    "second-earthquakes",
                    Disaster.EARTHQUAKE,
                    "second",
                    NOW,
                    latitude=-33.8,
                    longitude=151.2,
                ),
            )
        ),
    )
    service = _active_incidents_service(
        ProviderRegistry(
            (
                _registration("First earthquakes", first, Disaster.EARTHQUAKE),
                _registration("Second earthquakes", second, Disaster.EARTHQUAKE),
            )
        ),
        clock=lambda: NOW,
    )

    snapshot = await service.execute()

    assert {item.event_id for item in snapshot.incidents} == {"first", "second"}


@pytest.mark.asyncio
async def test_successful_provider_attempt_is_recorded_as_success() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.attempts: list[ProviderAttempt] = []

        async def record_provider_attempt(self, attempt: ProviderAttempt) -> None:
            self.attempts.append(attempt)

    provider = FakeWorldwideProvider(
        "earthquakes",
        ProviderBatch((_event("earthquakes", Disaster.EARTHQUAKE, "quake", NOW),)),
    )
    recorder = Recorder()
    service = _active_incidents_service(
        ProviderRegistry(
            (_registration("Earthquakes", provider, Disaster.EARTHQUAKE),)
        ),
        clock=lambda: NOW,
        provider_attempt_recorder=recorder,
    )

    await service.execute()

    attempt = next(
        attempt for attempt in recorder.attempts if attempt.source_id == "earthquakes"
    )
    assert attempt.outcome is ProviderAttemptOutcome.SUCCESS
