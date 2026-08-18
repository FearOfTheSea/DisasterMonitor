"""Ports for bounded, source-backed disaster information retrieval."""

from datetime import datetime
from typing import Protocol

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
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


class WorldwideDisasterProvider(Protocol):
    """Find bounded worldwide events without inventing a country."""

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[WorldwideDisasterEvent]: ...


class WorldwideSituationProvider(Protocol):
    """Retrieve situation evidence for a worldwide event without a country."""

    async def get_worldwide_situation_reports(
        self,
        event: WorldwideDisasterEvent,
        query: WorldwideDisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]: ...


class Clock(Protocol):
    """Injectable time source used by freshness and cache tests."""

    def now(self) -> datetime: ...
