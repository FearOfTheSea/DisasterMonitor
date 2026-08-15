"""Ports for bounded, source-backed disaster information retrieval."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.application.disaster import (
    DisasterQuery,
    GlobalDisasterEvent,
    GlobalEarthquakeQuery,
    ProviderBatch,
)
from disaster_monitor.domain.disaster import DisasterEvent, SituationReport


class DisasterEventProvider(Protocol):
    """Find recent candidate events for a normalized query."""

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]: ...


class SituationReportProvider(Protocol):
    """Retrieve situation updates for one selected event."""

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]: ...


class GlobalEarthquakeProvider(Protocol):
    """Find bounded worldwide earthquake events without inventing a country."""

    async def find_global_earthquakes(
        self, query: GlobalEarthquakeQuery, *, now: datetime
    ) -> ProviderBatch[GlobalDisasterEvent]: ...


class Clock(Protocol):
    """Injectable time source used by freshness and cache tests."""

    def now(self) -> datetime: ...
