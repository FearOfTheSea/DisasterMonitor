"""Compatibility facade for callers of the former earthquake-only service."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, cast

from disaster_monitor.application.disaster import (
    DisasterReport,
    GeographicScope,
    GlobalDisasterEvent,
    GlobalEarthquakeQuery,
    GlobalEventSelection,
    ProviderBatch,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.domain.disaster import Hazard


def _now_utc() -> datetime:
    return datetime.now(UTC)


class _LegacyProvider(Protocol):
    async def find_global_earthquakes(
        self, query: GlobalEarthquakeQuery, *, now: datetime
    ) -> ProviderBatch[GlobalDisasterEvent]: ...


class _LegacyEarthquakeProvider:
    def __init__(self, provider: object) -> None:
        self._provider = provider

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[GlobalDisasterEvent]:
        legacy_query = GlobalEarthquakeQuery(
            selection=GlobalEventSelection(query.selection),
            time_window_days=query.time_window_days,
            minimum_magnitude=query.minimum_magnitude or 4.5,
            limit=query.limit,
        )
        return await cast(_LegacyProvider, self._provider).find_global_earthquakes(
            legacy_query, now=now
        )


class GlobalEarthquakeReportService:
    """Adapt the removed earthquake-specific service to neutral orchestration."""

    def __init__(
        self,
        registration: ProviderRegistration,
        *,
        clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        capabilities = registration.capabilities
        if GeographicScope.WORLDWIDE not in capabilities.geographic_scopes:
            capabilities = replace(
                capabilities,
                geographic_scopes=frozenset(
                    (*capabilities.geographic_scopes, GeographicScope.WORLDWIDE)
                ),
            )
        adapted = replace(
            registration,
            provider=_LegacyEarthquakeProvider(registration.provider),
            capabilities=capabilities,
        )
        self._service = WorldwideDisasterReportService(
            ProviderRegistry((adapted,)), clock=clock
        )

    @classmethod
    def from_registry(
        cls, registry: ProviderRegistry, *, clock: Callable[[], datetime] = _now_utc
    ) -> "GlobalEarthquakeReportService | None":
        matches = tuple(
            registration
            for registration in registry.registrations
            if registration.configured
            and ProviderRole.EVENT_DISCOVERY in registration.capabilities.roles
            and Hazard.EARTHQUAKE in registration.capabilities.hazards
            and registration.capabilities.country_codes is None
            and callable(
                getattr(registration.provider, "find_global_earthquakes", None)
            )
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError(
                "Worldwide earthquake discovery has ambiguous provider authority."
            )
        return cls(matches[0], clock=clock)

    async def execute(self, query: GlobalEarthquakeQuery) -> DisasterReport:
        report = await self._service.execute(
            WorldwideDisasterQuery(
                hazard=Hazard.EARTHQUAKE,
                selection=query.selection.value,
                time_window_days=query.time_window_days,
                minimum_magnitude=query.minimum_magnitude,
                limit=query.limit,
            )
        )
        if report.response_type == "current_disaster_worldwide_verification_failed":
            return replace(
                report, response_type="current_disaster_global_verification_failed"
            )
        return report
