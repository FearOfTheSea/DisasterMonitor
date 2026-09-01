"""Typed authoritative weather-alert artifacts and read use case."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from disaster_monitor.application.ports.weather_alerts import (
        WeatherAlertProvider,
        WeatherAlertProviderIssue,
    )


class WeatherAlertSeverity(StrEnum):
    EXTREME = "extreme"
    SEVERE = "severe"
    MODERATE = "moderate"
    MINOR = "minor"
    UNKNOWN = "unknown"


class WeatherAlertUrgency(StrEnum):
    IMMEDIATE = "immediate"
    EXPECTED = "expected"
    FUTURE = "future"
    PAST = "past"
    UNKNOWN = "unknown"


class WeatherAlertCertainty(StrEnum):
    OBSERVED = "observed"
    LIKELY = "likely"
    POSSIBLE = "possible"
    UNLIKELY = "unlikely"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WeatherAlertCoordinate:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class WeatherAlertGeometry:
    """Exact source-supplied polygon rings; place names are never geocoded."""

    rings: tuple[tuple[WeatherAlertCoordinate, ...], ...]


@dataclass(frozen=True, slots=True)
class WeatherAlert:
    """A warning artifact, deliberately separate from physical disaster events."""

    provider_alert_id: str
    source_id: str
    publisher: str
    event: str
    headline: str | None
    severity: WeatherAlertSeverity
    urgency: WeatherAlertUrgency
    certainty: WeatherAlertCertainty
    sent: datetime | None
    effective: datetime | None
    onset: datetime | None
    expires: datetime | None
    affected_area: str
    geometry: WeatherAlertGeometry | None
    canonical_url: str | None
    retrieved_at: datetime
    attribution: str
    limitations: tuple[str, ...]


class WeatherAlertCoverageState(StrEnum):
    ALERTS_FOUND = "alerts_found"
    NO_ACTIVE_ALERTS = "no_active_alerts"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class WeatherAlertCoverage:
    source_id: str
    publisher: str
    state: WeatherAlertCoverageState
    detail: str
    geographic_scope: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeatherAlertsSnapshot:
    retrieved_at: datetime
    alerts: tuple[WeatherAlert, ...]
    coverage: WeatherAlertCoverage
    warnings: tuple["WeatherAlertProviderIssue", ...] = ()


NWS_SOURCE_ID = "nws-weather-alerts"
NWS_PUBLISHER = "NOAA/National Weather Service"
NWS_GEOGRAPHIC_SCOPE = "United States land areas served by the National Weather Service"
NWS_LIMITATIONS = (
    "Coverage is limited to active NWS alerts for United States land areas "
    "and is not global.",
    "The pull API can be delayed or unavailable; this layer is not a replacement "
    "for official local warning channels.",
    "Many zone-based alerts and watches have no polygon geometry. Missing geometry "
    "is not reconstructed from place names or zone labels.",
    "Alerts are warning artifacts and never confirm a flood, cyclone, wildfire, "
    "evacuation, casualty, or other physical disaster event.",
)


class WeatherAlertsService:
    """Read current warnings while preserving provider coverage state."""

    def __init__(
        self,
        provider: "WeatherAlertProvider",
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self) -> WeatherAlertsSnapshot:
        now = self._clock()
        batch = await self._provider.fetch_active_alerts(now=now)
        if batch.issue is not None and batch.issue.partial:
            state = WeatherAlertCoverageState.DEGRADED
            detail = (
                f"{len(batch.alerts)} active alert records were retained after a "
                "bounded provider limitation."
            )
        elif batch.issue is not None:
            state = WeatherAlertCoverageState.UNAVAILABLE
            detail = "The authoritative weather-alert source could not be retrieved."
        elif batch.alerts:
            state = WeatherAlertCoverageState.ALERTS_FOUND
            detail = f"{len(batch.alerts)} active alert record(s) were returned."
        else:
            state = WeatherAlertCoverageState.NO_ACTIVE_ALERTS
            detail = (
                "The bounded source request succeeded with no active alert records; "
                "this does not prove that no hazardous weather exists."
            )
        return WeatherAlertsSnapshot(
            retrieved_at=now,
            alerts=batch.alerts,
            coverage=WeatherAlertCoverage(
                source_id=NWS_SOURCE_ID,
                publisher=NWS_PUBLISHER,
                state=state,
                detail=detail,
                geographic_scope=NWS_GEOGRAPHIC_SCOPE,
                limitations=NWS_LIMITATIONS,
            ),
            warnings=(batch.issue,) if batch.issue is not None else (),
        )

    async def aclose(self) -> None:
        close = getattr(self._provider, "aclose", None)
        if close is not None:
            await close()
