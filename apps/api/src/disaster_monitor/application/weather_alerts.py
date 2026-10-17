"""Provider-neutral official warning read service and stable UI projection."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from disaster_monitor.application.ports.weather_alerts import (
    WeatherAlertBatch,
    WeatherAlertProviderIssue,
)
from disaster_monitor.application.warnings.lifecycle import reconcile_cap_messages
from disaster_monitor.domain.warnings import (
    ReconciledWarning,
    WarningLifecycleState,
)
from disaster_monitor.domain.warnings import (
    WarningCertainty as WeatherAlertCertainty,
)
from disaster_monitor.domain.warnings import (
    WarningSeverity as WeatherAlertSeverity,
)
from disaster_monitor.domain.warnings import (
    WarningUrgency as WeatherAlertUrgency,
)

if TYPE_CHECKING:
    from disaster_monitor.application.ports.weather_alerts import (
        WeatherAlertProvider,
        WeatherAlertProviderIssue,
    )


@dataclass(frozen=True, slots=True)
class WeatherAlertCoordinate:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class WeatherAlertGeometry:
    rings: tuple[tuple[WeatherAlertCoordinate, ...], ...]


@dataclass(frozen=True, slots=True)
class WeatherAlert:
    provider_alert_id: str
    source_id: str
    publisher: str
    event: str
    headline: str | None
    severity: WeatherAlertSeverity
    urgency: WeatherAlertUrgency
    certainty: WeatherAlertCertainty
    sent: datetime
    effective: datetime | None
    onset: datetime | None
    expires: datetime | None
    affected_area: str
    geometry: WeatherAlertGeometry | None
    canonical_url: str | None
    retrieved_at: datetime
    attribution: str
    limitations: tuple[str, ...]
    sender: str = "unknown"
    status: str = "actual"
    message_type: str = "alert"
    scope: str = "public"
    lifecycle_state: WarningLifecycleState = WarningLifecycleState.ACTIVE
    languages: tuple[str, ...] = ()
    event_codes: tuple[tuple[str, str], ...] = ()
    superseded_identifiers: tuple[str, ...] = ()
    profile: str | None = None
    signature_present: bool = False
    signature_verified: bool | None = None


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
    "Coverage is limited to NWS alerts for United States land areas and is not global.",
    "The pull API can be delayed or unavailable; this layer is not a replacement "
    "for official local warning channels.",
    "Many zone-based alerts and watches have no polygon geometry. Missing geometry "
    "is not reconstructed from place names or zone labels.",
    "Alerts are warning artifacts and never confirm a physical disaster event or "
    "impact.",
)


class WeatherAlertsService:
    def __init__(
        self,
        provider: "WeatherAlertProvider",
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._batch: WeatherAlertBatch | None = None
        self._retrieved_at: datetime | None = None
        self._checked_at: datetime | None = None
        self._last_success: WeatherAlertBatch | None = None
        self._inflight: asyncio.Task[WeatherAlertBatch] | None = None

    async def current_messages(self) -> WeatherAlertBatch:
        now = self._clock()
        if (
            self._batch
            and self._checked_at
            and now - self._checked_at < timedelta(minutes=2)
        ):
            return self._batch
        if self._inflight is None:
            self._inflight = asyncio.create_task(self._retrieve(now))
        task = self._inflight
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._inflight = None

    async def _retrieve(self, now: datetime) -> WeatherAlertBatch:
        try:
            batch = await self._provider.fetch_active_alerts(now=now)
        except Exception:
            batch = WeatherAlertBatch(
                issue=WeatherAlertProviderIssue(
                    "warning_retrieval_failed",
                    "Warning retrieval failed.",
                    retryable=True,
                )
            )
        if batch.issue is None:
            self._last_success = batch
            self._retrieved_at = now
        elif not batch.alerts and self._last_success and batch.issue:
            batch = replace(
                self._last_success,
                issue=replace(
                    batch.issue,
                    partial=True,
                    detail=batch.issue.detail
                    + " Retained the last successful messages; validity is rechecked.",
                ),
            )
        elif batch.alerts:
            self._retrieved_at = now
        self._batch, self._checked_at = batch, now
        return batch

    async def execute(self) -> WeatherAlertsSnapshot:
        now = self._clock()
        batch = await self.current_messages()
        alerts = tuple(
            _project_warning(item)
            for item in reconcile_cap_messages(batch.alerts, now=now)
        )
        if batch.issue is not None and batch.issue.partial:
            state = WeatherAlertCoverageState.DEGRADED
            detail = (
                f"{len(alerts)} warning records were retained after a bounded "
                "provider limitation."
            )
        elif batch.issue is not None:
            state = WeatherAlertCoverageState.UNAVAILABLE
            detail = "The authoritative warning source could not be retrieved."
        elif alerts:
            state = WeatherAlertCoverageState.ALERTS_FOUND
            detail = f"{len(alerts)} current warning record(s) were returned."
        else:
            state = WeatherAlertCoverageState.NO_ACTIVE_ALERTS
            detail = (
                "The bounded source request succeeded with no current warning records; "
                "this does not prove that no hazard exists."
            )
        return WeatherAlertsSnapshot(
            retrieved_at=self._retrieved_at or now,
            alerts=alerts,
            coverage=WeatherAlertCoverage(
                source_id=getattr(self._provider, "source_id", NWS_SOURCE_ID),
                publisher=getattr(self._provider, "publisher", NWS_PUBLISHER),
                state=state,
                detail=detail,
                geographic_scope=getattr(
                    self._provider, "geographic_scope", NWS_GEOGRAPHIC_SCOPE
                ),
                limitations=getattr(self._provider, "limitations", NWS_LIMITATIONS),
            ),
            warnings=(batch.issue,) if batch.issue is not None else (),
        )

    async def aclose(self) -> None:
        if self._inflight is not None:
            self._inflight.cancel()
            await asyncio.gather(self._inflight, return_exceptions=True)
        close = getattr(self._provider, "aclose", None)
        if close is not None:
            await close()


def _project_warning(value: ReconciledWarning) -> WeatherAlert:
    alert = value.alert
    info = alert.infos[0] if alert.infos else None
    areas = tuple(area for block in alert.infos for area in block.areas)
    polygons = tuple(geometry for area in areas for geometry in area.polygons)
    rings = tuple(
        tuple(
            WeatherAlertCoordinate(item.latitude, item.longitude)
            for item in ring.coordinates
        )
        for geometry in polygons
        for polygon in geometry.polygons
        for ring in (polygon.exterior, *polygon.holes)
    )
    return WeatherAlert(
        provider_alert_id=alert.identifier,
        source_id=alert.source_id,
        publisher=alert.publisher,
        sender=alert.sender,
        event=info.event if info is not None else "Cancellation",
        headline=info.headline if info is not None else None,
        severity=info.severity if info is not None else WeatherAlertSeverity.UNKNOWN,
        urgency=info.urgency if info is not None else WeatherAlertUrgency.UNKNOWN,
        certainty=info.certainty if info is not None else WeatherAlertCertainty.UNKNOWN,
        sent=alert.sent,
        effective=info.effective if info is not None else None,
        onset=info.onset if info is not None else None,
        expires=info.expires if info is not None else None,
        affected_area=(
            "; ".join(dict.fromkeys(area.description for area in areas))
            or "Not specified"
        ),
        geometry=WeatherAlertGeometry(rings) if rings else None,
        canonical_url=alert.canonical_url,
        retrieved_at=alert.retrieved_at,
        attribution=alert.attribution,
        limitations=alert.limitations,
        status=alert.status.value,
        message_type=alert.message_type.value,
        scope=alert.scope.value,
        lifecycle_state=value.state,
        languages=tuple(dict.fromkeys(block.language for block in alert.infos)),
        event_codes=tuple(
            dict.fromkeys(code for block in alert.infos for code in block.event_codes)
        ),
        superseded_identifiers=value.superseded_identifiers,
        profile=alert.profile,
        signature_present=alert.signature_present,
        signature_verified=alert.signature_verified,
    )


__all__ = [
    "NWS_GEOGRAPHIC_SCOPE",
    "NWS_LIMITATIONS",
    "NWS_PUBLISHER",
    "NWS_SOURCE_ID",
    "WeatherAlert",
    "WeatherAlertCertainty",
    "WeatherAlertCoordinate",
    "WeatherAlertCoverage",
    "WeatherAlertCoverageState",
    "WeatherAlertGeometry",
    "WeatherAlertSeverity",
    "WeatherAlertsService",
    "WeatherAlertsSnapshot",
    "WeatherAlertUrgency",
]
