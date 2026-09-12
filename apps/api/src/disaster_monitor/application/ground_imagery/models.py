"""Stable application records for one event-focused imagery request."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.application.ground_imagery.resolve_region import RegionResolution
from disaster_monitor.application.ground_imagery.select_observations import (
    SelectionResult,
)
from disaster_monitor.application.ground_imagery.temporal_policy import (
    ImpactOnset,
    TemporalPlan,
)
from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.observations import (
    Observation,
    Sensor,
    TemporalRole,
)
from disaster_monitor.domain.imagery.regions import MultiPolygon


class GroundImageryRequestState(StrEnum):
    """Aggregate state; sensor and role gaps remain in the detail records."""

    QUEUED = "queued"
    RESOLVING = "resolving"
    SEARCHING = "searching"
    ASSESSING = "assessing"
    READY = "ready"
    PARTIAL = "partial"
    NEEDS_REGION = "needs_region"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class GroundImageryRequestInput:
    incident_id: str
    reference_time: datetime
    sensors: tuple[Sensor, ...] = (Sensor.SENTINEL_1, Sensor.SENTINEL_2)
    user_region: MultiPolygon | None = None
    context_margin_km: float | None = None
    fallback_radius_km: float | None = None
    owner_scope: str = "local"
    idempotency_key: str | None = None
    onset_override: ImpactOnset | None = None

    def __post_init__(self) -> None:
        if not self.incident_id.strip() or not self.owner_scope.strip():
            raise ValueError("An imagery request requires incident and owner scope.")
        if (
            self.reference_time.tzinfo is None
            or self.reference_time.utcoffset() is None
        ):
            raise ValueError(
                "An imagery request reference time must be timezone-aware."
            )
        if not self.sensors or len(set(self.sensors)) != len(self.sensors):
            raise ValueError("An imagery request requires unique sensors.")
        if any(not isinstance(sensor, Sensor) for sensor in self.sensors):
            raise ValueError("The imagery request contains an unsupported sensor.")
        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("An imagery idempotency key must not be empty.")


@dataclass(frozen=True, slots=True)
class SensorSearchStatus:
    sensor: Sensor
    scanned_count: int
    scan_complete: bool
    next_cursor: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        if self.scanned_count < 0:
            raise ValueError("A catalog scan count cannot be negative.")


@dataclass(frozen=True, slots=True)
class ImageryArtifactReference:
    """Immutable artifact metadata bound to a request selection and grid."""

    artifact_id: str
    selection_id: str
    sensor: Sensor
    role: TemporalRole
    output_kind: str
    content_type: str
    storage_key: str
    byte_count: int
    sha256: str
    source_product_ids: tuple[str, ...]
    grid: ImageryGrid
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not self.artifact_id.strip()
            or not self.selection_id.strip()
            or not self.output_kind.strip()
            or not self.storage_key.strip()
            or not self.sha256.strip()
        ):
            raise ValueError("An imagery artifact requires stable identity metadata.")
        if self.byte_count < 1 or not self.source_product_ids:
            raise ValueError("An imagery artifact requires bounded content provenance.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Imagery artifact timestamps must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class GroundImageryRequest:
    request_id: str
    request_version: int
    incident_id: str
    disaster: Disaster
    reference_time: datetime
    requested_sensors: tuple[Sensor, ...]
    region_resolution: RegionResolution
    temporal_plan: TemporalPlan
    candidates: tuple[Observation, ...]
    search_status: tuple[SensorSearchStatus, ...]
    selection: SelectionResult | None
    state: GroundImageryRequestState
    reason_codes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    owner_scope: str = "local"
    watch_enabled: bool = False
    watch_interval_seconds: int | None = None
    next_check_at: datetime | None = None
    artifacts: tuple[ImageryArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        if not self.request_id.strip() or self.request_version < 1:
            raise ValueError(
                "An imagery request requires a positive versioned identity."
            )
        for value in (self.reference_time, self.created_at, self.updated_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Imagery request timestamps must be timezone-aware.")
        if self.updated_at < self.created_at:
            raise ValueError("An imagery request cannot be updated before creation.")

    def observations_for(self, sensor: Sensor | None = None) -> tuple[Observation, ...]:
        if sensor is None:
            return self.candidates
        return tuple(item for item in self.candidates if item.sensor is sensor)

    def sensor_search(self, sensor: Sensor) -> SensorSearchStatus:
        for status in self.search_status:
            if status.sensor is sensor:
                return status
        raise KeyError(sensor.value)

    def selected_observation(
        self, sensor: Sensor, role: TemporalRole
    ) -> Observation | None:
        if self.selection is None:
            return None
        return self.selection.for_sensor(sensor).for_role(role).observation
