"""Source-backed disaster event and geometry models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import asin, cos, isfinite, radians, sin, sqrt

from disaster_monitor.domain.disaster_types import (
    Country,
    Disaster,
    EventGeographyStatus,
    ProviderTier,
    _is_aware,
)
from disaster_monitor.domain.evidence_types import (
    EventAssignmentStatus,
    SourceReference,
)


class MeasurementKind(StrEnum):
    """Known source-reported measurements shared by disaster policies."""

    MAGNITUDE = "magnitude"
    INTENSITY = "intensity"
    DEPTH = "depth"
    PROVIDER_SIGNIFICANCE = "provider_significance"
    CONFIDENCE = "confidence"
    FIRE_RADIATIVE_POWER = "fire_radiative_power"
    SEVERITY = "severity"


@dataclass(frozen=True, slots=True)
class EventMeasurement:
    """One typed, source-backed measurement attached to an event."""

    kind: MeasurementKind
    value: float | str
    unit: str | None = None
    source: SourceReference = field(kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MeasurementKind):
            raise TypeError("An event measurement requires a typed measurement kind.")
        if not isinstance(self.source, SourceReference):
            raise TypeError("An event measurement requires source provenance.")
        if isinstance(self.value, bool) or (
            isinstance(self.value, float) and not isfinite(self.value)
        ):
            raise ValueError("An event measurement value must be finite.")
        if not isinstance(self.value, (int, float, str)):
            raise TypeError("An event measurement value has an unsupported type.")
        if self.unit is not None and not self.unit.strip():
            raise ValueError("An event measurement unit must not be empty.")


class EventGeometryKind(StrEnum):
    """Authoritative geometry shape available for an event."""

    POINT = "point"
    AREA = "area"
    TRACK = "track"
    DESCRIPTIVE = "descriptive"


@dataclass(frozen=True, slots=True)
class EventCoordinate:
    """One WGS84 coordinate preserved exactly as supplied by a source."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if (
            not isfinite(self.latitude)
            or not isfinite(self.longitude)
            or not -90 <= self.latitude <= 90
            or not -180 <= self.longitude <= 180
        ):
            raise ValueError("An event coordinate is outside the WGS84 extent.")


def geographic_distance_km(first: EventCoordinate, second: EventCoordinate) -> float:
    """Return deterministic great-circle distance between source coordinates."""
    first_latitude = radians(first.latitude)
    second_latitude = radians(second.latitude)
    latitude_delta = radians(second.latitude - first.latitude)
    longitude_delta = radians(second.longitude - first.longitude)
    value = sin(latitude_delta / 2) ** 2 + (
        cos(first_latitude) * cos(second_latitude) * sin(longitude_delta / 2) ** 2
    )
    return 2 * 6_371.0088 * asin(min(1.0, sqrt(value)))


class CycloneMapSemanticRole(StrEnum):
    """Explicit meaning of geometry supplemental to a selected cyclone."""

    PROVISIONAL_TRACK = "provisional_track"
    FORECAST_TRACK = "forecast_track"
    UNCERTAINTY_AREA = "uncertainty_area"
    WIND_RADII = "wind_radii"


class CycloneMapGeometryKind(StrEnum):
    """Renderable geometry kinds admitted for supplemental cyclone context."""

    POINT = "point"
    TRACK = "track"
    AREA = "area"


@dataclass(frozen=True, slots=True)
class CycloneMapCoordinate:
    """One exact source coordinate and its product validity time, when supplied."""

    latitude: float
    longitude: float
    valid_at: datetime | None = None

    def __post_init__(self) -> None:
        EventCoordinate(self.latitude, self.longitude)
        if self.valid_at is not None and not _is_aware(self.valid_at):
            raise ValueError("A cyclone map coordinate time must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class CycloneMapLayer:
    """Source-backed map context kept separate from event occurrence geometry."""

    layer_id: str
    semantic_role: CycloneMapSemanticRole
    geometry_kind: CycloneMapGeometryKind
    coordinates: tuple[CycloneMapCoordinate, ...]
    source: SourceReference
    issued_at: datetime
    valid_from: datetime | None
    valid_to: datetime | None
    storm_id: str
    provisional: bool
    limitation: str
    reconciliation: str
    wind_threshold: float | None = None
    wind_threshold_unit: str | None = None

    def __post_init__(self) -> None:
        if not self.layer_id.strip() or not self.storm_id.strip():
            raise ValueError("A cyclone map layer requires stable layer and storm IDs.")
        if not isinstance(self.semantic_role, CycloneMapSemanticRole):
            raise TypeError("A cyclone map layer requires a typed semantic role.")
        if not isinstance(self.geometry_kind, CycloneMapGeometryKind):
            raise TypeError("A cyclone map layer requires a typed geometry kind.")
        if not isinstance(self.source, SourceReference):
            raise TypeError("A cyclone map layer requires source provenance.")
        if not _is_aware(self.issued_at) or any(
            value is not None and not _is_aware(value)
            for value in (self.valid_from, self.valid_to)
        ):
            raise ValueError("Cyclone map layer timestamps must be timezone-aware.")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("A cyclone map layer validity interval is reversed.")
        if not isinstance(self.provisional, bool):
            raise TypeError("Cyclone map provisional metadata must be boolean.")
        if not self.limitation.strip() or not self.reconciliation.strip():
            raise ValueError(
                "A cyclone map layer requires limitation and reconciliation text."
            )
        if self.geometry_kind is CycloneMapGeometryKind.POINT:
            valid_geometry = len(self.coordinates) == 1
        elif self.geometry_kind is CycloneMapGeometryKind.TRACK:
            valid_geometry = len(self.coordinates) >= 2
        else:
            valid_geometry = len(self.coordinates) >= 3
        if not valid_geometry:
            raise ValueError("Cyclone map layer coordinate cardinality is invalid.")
        if any(not isinstance(item, CycloneMapCoordinate) for item in self.coordinates):
            raise TypeError("A cyclone map layer requires typed coordinates.")
        if self.semantic_role is CycloneMapSemanticRole.PROVISIONAL_TRACK:
            if (
                self.geometry_kind is not CycloneMapGeometryKind.TRACK
                or not self.provisional
            ):
                raise ValueError(
                    "Provisional track layers require track geometry and a "
                    "provisional flag."
                )
        elif self.provisional:
            raise ValueError("Forecast and uncertainty layers cannot be provisional.")
        if self.semantic_role is CycloneMapSemanticRole.FORECAST_TRACK:
            if self.geometry_kind is not CycloneMapGeometryKind.TRACK:
                raise ValueError("Forecast track layers require track geometry.")
            if any(item.valid_at is None for item in self.coordinates):
                raise ValueError("Forecast track points require source validity times.")
        if (
            self.semantic_role is CycloneMapSemanticRole.UNCERTAINTY_AREA
            and self.geometry_kind is not CycloneMapGeometryKind.AREA
        ):
            raise ValueError("Uncertainty layers require area geometry.")
        if self.semantic_role is CycloneMapSemanticRole.WIND_RADII:
            if (
                self.geometry_kind is not CycloneMapGeometryKind.AREA
                or self.wind_threshold is None
                or isinstance(self.wind_threshold, bool)
                or not isfinite(self.wind_threshold)
                or self.wind_threshold <= 0
                or not self.wind_threshold_unit
                or not self.wind_threshold_unit.strip()
            ):
                raise ValueError(
                    "Wind-radii layers require area geometry and a positive "
                    "source threshold with units."
                )
        elif self.wind_threshold is not None or self.wind_threshold_unit is not None:
            raise ValueError("Only wind-radii layers may carry wind thresholds.")


@dataclass(frozen=True, slots=True)
class EventGeometry:
    """A source-backed point, area, track, or descriptive-only location."""

    kind: EventGeometryKind
    source: SourceReference
    coordinates: tuple[EventCoordinate, ...] = ()
    description: str | None = None
    estimated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.estimated, bool):
            raise TypeError("Event geometry estimation metadata must be boolean.")
        if self.kind is EventGeometryKind.POINT and len(self.coordinates) != 1:
            raise ValueError("A point event geometry requires one coordinate.")
        if self.kind is EventGeometryKind.AREA and len(self.coordinates) < 3:
            raise ValueError("An area event geometry requires a perimeter.")
        if self.kind is EventGeometryKind.TRACK and len(self.coordinates) < 2:
            raise ValueError("A track event geometry requires two coordinates.")
        if self.kind is EventGeometryKind.DESCRIPTIVE:
            if self.coordinates or not self.description or not self.description.strip():
                raise ValueError(
                    "Descriptive event geometry requires only a description."
                )
        elif self.description is not None and not self.description.strip():
            raise ValueError("An event geometry description must not be empty.")


def point_event_geometry(
    latitude: float,
    longitude: float,
    source: SourceReference,
    *,
    estimated: bool = False,
) -> EventGeometry:
    """Build point geometry without changing or deriving its coordinates."""
    return EventGeometry(
        kind=EventGeometryKind.POINT,
        source=source,
        coordinates=(EventCoordinate(latitude, longitude),),
        estimated=estimated,
    )


def descriptive_event_geometry(
    description: str, source: SourceReference
) -> EventGeometry:
    """Build source-backed descriptive geometry when no authoritative shape exists."""
    return EventGeometry(
        kind=EventGeometryKind.DESCRIPTIVE,
        source=source,
        description=description,
    )


@dataclass(frozen=True, slots=True)
class DisasterEvent:
    """A normalized source-backed disaster event."""

    event_id: str
    disaster: Disaster
    location: str
    country: Country
    event_time: datetime
    source: SourceReference
    geometry: EventGeometry | None = None
    measurements: tuple[EventMeasurement, ...] = ()
    provider_ids: tuple[str, ...] = ()
    geography_status: EventGeographyStatus = EventGeographyStatus.IN_COUNTRY
    provider_tier: ProviderTier = ProviderTier.SECONDARY

    def __post_init__(self) -> None:
        if not isinstance(self.provider_tier, ProviderTier):
            raise TypeError("A disaster event requires a typed provider tier.")
        if not isinstance(self.measurements, tuple) or any(
            not isinstance(item, EventMeasurement) for item in self.measurements
        ):
            raise TypeError("A disaster event requires typed measurements.")

    def measurement(self, kind: MeasurementKind) -> EventMeasurement | None:
        """Return the first retained measurement of a typed kind."""
        for measurement in self.measurements:
            if measurement.kind is kind:
                return measurement
        return None

    def measurements_of(self, kind: MeasurementKind) -> tuple[EventMeasurement, ...]:
        """Return all retained observations of a typed measurement kind."""
        return tuple(item for item in self.measurements if item.kind is kind)

    def has_provider_id(self, value: str) -> bool:
        """Return whether a provider-specific identifier belongs to this event."""
        normalized = value.strip().lower()
        identifiers = {
            item.strip().lower()
            for item in (self.event_id, *self.provider_ids)
            if item.strip()
        }
        if ":" in normalized:
            return normalized in identifiers
        return normalized in {
            identifier.partition(":")[2] if ":" in identifier else identifier
            for identifier in identifiers
        }


@dataclass(frozen=True, slots=True)
class EarthquakeEvent(DisasterEvent):
    """Earthquake-only sequence details kept out of shared event fields."""

    is_aftershock: bool = False
    parent_event_id: str | None = None
    sequence_id: str | None = None

    def __post_init__(self) -> None:
        if self.disaster is not Disaster.EARTHQUAKE:
            raise ValueError("EarthquakeEvent requires the earthquake disaster.")


@dataclass(frozen=True, slots=True)
class EventObservationAssignment:
    """Auditable assignment of one provider observation to a physical event."""

    observation_key: str
    physical_event_id: str
    status: EventAssignmentStatus
    rationale: str
    compatible_observation_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PhysicalEventIdentity:
    """One conservatively resolved physical event and all source observations."""

    physical_event_id: str
    event: DisasterEvent
    observations: tuple[DisasterEvent, ...]
    assignments: tuple[EventObservationAssignment, ...]

    def __post_init__(self) -> None:
        if not self.observations:
            raise ValueError("A physical event requires at least one observation.")
        if self.event.source not in {item.source for item in self.observations}:
            raise ValueError("A physical event must retain an observed event source.")
        if self.event.geometry is not None and not any(
            item.geometry == self.event.geometry for item in self.observations
        ):
            raise ValueError(
                "A physical event geometry must retain an observed geometry source."
            )
        for measurement in self.event.measurements:
            if not any(measurement in item.measurements for item in self.observations):
                raise ValueError(
                    "A physical event measurement must retain its observation source."
                )


@dataclass(frozen=True, slots=True)
class PhysicalEventIdentityResult:
    """Deterministic partition plus any deliberately unresolved assignments."""

    physical_events: tuple[PhysicalEventIdentity, ...]
    ambiguous_assignments: tuple[EventObservationAssignment, ...] = ()
