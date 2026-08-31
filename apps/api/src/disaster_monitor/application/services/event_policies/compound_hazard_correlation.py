"""Bounded deterministic context between already-distinct disaster events."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from disaster_monitor.domain.disaster import (
    Disaster,
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
    SourceReference,
    geographic_distance_km,
)

ASSOCIATION_LIMITATION = "Spatial and temporal proximity does not establish causation."
MAX_CORRELATIONS = 100


class CompoundHazardRelationship(StrEnum):
    """The only relationship meaning supported by v1."""

    SPATIOTEMPORAL_ASSOCIATION = "spatiotemporal_association"


class CorrelatableIncident(Protocol):
    """Narrow incident projection consumed by compound-hazard policy."""

    @property
    def event_id(self) -> str: ...

    @property
    def physical_event_id(self) -> str | None: ...

    @property
    def disaster(self) -> Disaster: ...

    @property
    def event_time(self) -> datetime: ...

    @property
    def geometry(self) -> EventGeometry | None: ...

    @property
    def source(self) -> SourceReference: ...


@dataclass(frozen=True, slots=True)
class CompoundHazardCorrelation:
    """Immutable explanatory association with stable participant identity."""

    correlation_id: str
    rule_id: str
    relationship: CompoundHazardRelationship
    first_event_id: str
    first_physical_event_id: str | None
    first_disaster: Disaster
    second_event_id: str
    second_physical_event_id: str | None
    second_disaster: Disaster
    distance_km: float
    time_delta_seconds: int
    source_ids: tuple[str, ...]
    summary: str
    limitation: str = ASSOCIATION_LIMITATION


@dataclass(frozen=True, slots=True)
class _CorrelationRule:
    rule_id: str
    first_disaster: Disaster
    second_disaster: Disaster
    maximum_distance_km: float
    maximum_time_seconds: int
    require_second_at_or_after_first: bool


_V1_RULES = (
    _CorrelationRule(
        "compound-hazard:earthquake-landslide:v1",
        Disaster.EARTHQUAKE,
        Disaster.LANDSLIDE,
        150.0,
        72 * 3600,
        True,
    ),
    _CorrelationRule(
        "compound-hazard:tropical-cyclone-flood:v1",
        Disaster.TROPICAL_CYCLONE,
        Disaster.FLOOD,
        300.0,
        72 * 3600,
        False,
    ),
)


class CompoundHazardCorrelationService:
    """Apply the explicit v1 allowlist without changing event identity or evidence."""

    def correlate(
        self, incidents: Sequence[CorrelatableIncident]
    ) -> tuple[CompoundHazardCorrelation, ...]:
        correlations: dict[str, CompoundHazardCorrelation] = {}
        for index, first_candidate in enumerate(incidents):
            for second_candidate in incidents[index + 1 :]:
                correlation = _correlate_pair(first_candidate, second_candidate)
                if correlation is not None:
                    correlations[correlation.correlation_id] = correlation
        return tuple(
            sorted(
                correlations.values(),
                key=lambda item: (
                    item.rule_id,
                    item.first_event_id,
                    item.second_event_id,
                    item.correlation_id,
                ),
            )[:MAX_CORRELATIONS]
        )


def _correlate_pair(
    first_candidate: CorrelatableIncident,
    second_candidate: CorrelatableIncident,
) -> CompoundHazardCorrelation | None:
    if first_candidate.disaster is second_candidate.disaster:
        return None
    rule = next(
        (
            item
            for item in _V1_RULES
            if {first_candidate.disaster, second_candidate.disaster}
            == {item.first_disaster, item.second_disaster}
        ),
        None,
    )
    if rule is None:
        return None
    first, second = (
        (first_candidate, second_candidate)
        if first_candidate.disaster is rule.first_disaster
        else (second_candidate, first_candidate)
    )
    first_identity = _identity(first)
    second_identity = _identity(second)
    if first_identity == second_identity:
        return None
    first_point = _point(first)
    second_point = _point(second)
    if first_point is None or second_point is None:
        return None
    signed_time_delta = (second.event_time - first.event_time).total_seconds()
    if rule.require_second_at_or_after_first and signed_time_delta < 0:
        return None
    time_delta_seconds = abs(signed_time_delta)
    if time_delta_seconds > rule.maximum_time_seconds:
        return None
    distance = geographic_distance_km(first_point, second_point)
    if distance > rule.maximum_distance_km:
        return None
    correlation_material = "|".join((rule.rule_id, first_identity, second_identity))
    correlation_id = (
        f"compound-correlation:v1:"
        f"{sha256(correlation_material.encode('utf-8')).hexdigest()[:20]}"
    )
    rounded_distance = round(distance, 1)
    rounded_seconds = int(round(time_delta_seconds))
    first_label = first.disaster.value.replace("_", " ").capitalize()
    second_label = second.disaster.value.replace("_", " ")
    return CompoundHazardCorrelation(
        correlation_id=correlation_id,
        rule_id=rule.rule_id,
        relationship=CompoundHazardRelationship.SPATIOTEMPORAL_ASSOCIATION,
        first_event_id=first.event_id,
        first_physical_event_id=first.physical_event_id,
        first_disaster=first.disaster,
        second_event_id=second.event_id,
        second_physical_event_id=second.physical_event_id,
        second_disaster=second.disaster,
        distance_km=rounded_distance,
        time_delta_seconds=rounded_seconds,
        source_ids=tuple(sorted({first.source.source_id, second.source.source_id})),
        summary=(
            f"{first_label} {first.event_id} and {second_label} {second.event_id} "
            f"are approximately {rounded_distance:g} km and "
            f"{_elapsed_text(rounded_seconds)} apart."
        ),
    )


def _identity(incident: CorrelatableIncident) -> str:
    if incident.physical_event_id and incident.physical_event_id.strip():
        return incident.physical_event_id.strip().casefold()
    return (
        f"source-event:{incident.source.source_id.strip().casefold()}:"
        f"{incident.event_id.strip().casefold()}"
    )


def _point(incident: CorrelatableIncident) -> EventCoordinate | None:
    geometry = incident.geometry
    if geometry is None or geometry.kind is not EventGeometryKind.POINT:
        return None
    return geometry.coordinates[0]


def _elapsed_text(seconds: int) -> str:
    if seconds < 3600:
        return "less than 1 hour"
    hours = round(seconds / 3600)
    return f"{hours} hour" if hours == 1 else f"{hours} hours"
