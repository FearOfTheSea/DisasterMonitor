"""Generic normalized-observation identity and physical-event partitioning."""

from collections import deque
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC
from hashlib import sha256

from disaster_monitor.domain.disaster import (
    DisasterEvent,
    EventAssignmentStatus,
    EventCoordinate,
    EventGeometryKind,
    EventObservationAssignment,
    MeasurementKind,
    PhysicalEventIdentity,
    PhysicalEventIdentityResult,
    geographic_distance_km,
)


def event_point(event: DisasterEvent) -> EventCoordinate | None:
    geometry = event.geometry
    if geometry is None or geometry.kind is not EventGeometryKind.POINT:
        return None
    return geometry.coordinates[0]


def distance_km(first: DisasterEvent, second: DisasterEvent) -> float | None:
    first_point = event_point(first)
    second_point = event_point(second)
    if first_point is None or second_point is None:
        return None
    return geographic_distance_km(first_point, second_point)


def distance_to_coordinates(
    event: DisasterEvent, latitude: float, longitude: float
) -> float | None:
    point = event_point(event)
    if point is None or event.geometry is None:
        return None
    target = replace(
        event,
        geometry=replace(
            event.geometry,
            coordinates=(replace(point, latitude=latitude, longitude=longitude),),
        ),
    )
    return distance_km(event, target)


def measurement(event: DisasterEvent, kind: MeasurementKind) -> float | str | None:
    value = event.measurement(kind)
    return value.value if value is not None else None


def qualified_identifier(event: DisasterEvent, identifier: str) -> str:
    normalized = identifier.strip().lower()
    if ":" in normalized:
        return normalized
    return f"{event.source.source_id.lower()}:{normalized}"


def _admitted_provider_identifier(identifier: str) -> str | None:
    """Admit only namespaced event identifiers at the identity boundary.

    Provider catalogs also expose lineage labels such as ``GDACS`` or ``IRWIN``.
    Those labels identify a source family, not one event, and must never be used
    as cross-record identity evidence.
    """
    normalized = identifier.strip().lower()
    if not normalized or ":" not in normalized:
        return None
    namespace, value = normalized.split(":", 1)
    if not namespace or not value:
        return None
    return normalized


def provider_identifiers(event: DisasterEvent) -> set[str]:
    identifiers = {qualified_identifier(event, event.event_id)}
    identifiers.update(
        admitted
        for item in (*event.provider_ids, *event.lineage_ids)
        if (admitted := _admitted_provider_identifier(item)) is not None
    )
    return identifiers


def event_observation_key(event: DisasterEvent) -> str:
    """Return an immutable key for one provider event identity.

    Geometry, titles, timestamps, and source publication metadata can be revised
    by a provider.  The provider event identifier is the durable observation
    identity; mutable fields remain evidence attached to that identity.
    """
    material = "|".join(
        (
            event.source.source_id.lower(),
            event.event_id.lower(),
            event.disaster.value,
            event.country.alpha3_code.lower(),
        )
    )
    digest = sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"observation:{event.source.source_id.lower()}:{digest}"


def event_order_key(event: DisasterEvent) -> tuple[str, str, str, str]:
    return (
        event.disaster.value,
        event.country.alpha3_code,
        event.event_time.astimezone(UTC).isoformat(),
        event_observation_key(event),
    )


def merge_event(events: list[DisasterEvent]) -> DisasterEvent:
    ordered = sorted(events, key=event_order_key)
    if len(ordered) == 1:
        return ordered[0]
    preferred = max(
        ordered,
        key=lambda event: (
            event.provider_tier.precedence,
            event.source.effective_at,
            event_observation_key(event),
        ),
    )
    measurements = tuple(
        sorted(
            set(item for event in ordered for item in event.measurements),
            key=lambda item: (
                -next(
                    event.provider_tier.precedence
                    for event in ordered
                    if item.source == event.source
                ),
                item.kind.value,
                item.unit or "",
                str(item.value),
                item.source.source_id,
                item.source.canonical_url,
            ),
        )
    )
    geometry = preferred.geometry or next(
        (event.geometry for event in ordered if event.geometry is not None), None
    )
    return replace(
        preferred,
        geometry=geometry,
        measurements=measurements,
        provider_ids=tuple(
            sorted(
                {
                    identifier
                    for event in ordered
                    for identifier in (event.event_id, *event.provider_ids)
                }
            )
        ),
        lineage_ids=tuple(
            sorted({lineage for event in ordered for lineage in event.lineage_ids})
        ),
    )


def _physical_event_id(events: tuple[DisasterEvent, ...]) -> str:
    if not events:
        raise ValueError("A physical event identity requires observations.")
    first = max(events, key=event_observation_key)
    # The identity is anchored to one deterministic immutable observation, rather
    # than the complete corroborating set.  Choosing the upper bound means an
    # earlier-sorting corroboration enriches evidence without replacing the
    # established ID.  Durable projection assignments remain authoritative when
    # an already persisted event is reconciled across refreshes.
    material = event_observation_key(first)
    digest = sha256(material.encode("utf-8")).hexdigest()[:20]
    return (
        f"physical-event:{first.disaster.value}:"
        f"{first.country.alpha3_code.lower()}:{digest}"
    )


def identify_physical_events(
    events: tuple[DisasterEvent, ...],
    *,
    equivalent: Callable[[DisasterEvent, DisasterEvent], bool],
    merge: Callable[[list[DisasterEvent]], DisasterEvent] = merge_event,
) -> PhysicalEventIdentityResult:
    """Partition observations without order-dependent transitive merging."""
    ordered = tuple(sorted(events, key=event_order_key))
    compatible: dict[str, set[str]] = {
        event_observation_key(event): set() for event in ordered
    }
    by_key = {event_observation_key(event): event for event in ordered}
    for index, first in enumerate(ordered):
        first_key = event_observation_key(first)
        for second in ordered[index + 1 :]:
            if not equivalent(first, second):
                continue
            second_key = event_observation_key(second)
            compatible[first_key].add(second_key)
            compatible[second_key].add(first_key)

    components: list[tuple[str, ...]] = []
    remaining = set(by_key)
    while remaining:
        start = min(remaining)
        queue = deque((start,))
        component: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in component:
                continue
            component.add(current)
            queue.extend(sorted(compatible[current] - component))
        remaining -= component
        components.append(tuple(sorted(component)))

    identities: list[PhysicalEventIdentity] = []
    ambiguous_assignments: list[EventObservationAssignment] = []
    for component_keys in sorted(components):
        pair_count = len(component_keys) * (len(component_keys) - 1) // 2
        actual_pairs = sum(len(compatible[key]) for key in component_keys) // 2
        is_complete = actual_pairs == pair_count
        groups = (
            (component_keys,)
            if is_complete
            else tuple((key,) for key in component_keys)
        )
        for group in groups:
            observations = tuple(by_key[key] for key in group)
            physical_event_id = _physical_event_id(observations)
            assignments: list[EventObservationAssignment] = []
            for key in group:
                status = (
                    EventAssignmentStatus.ASSIGNED
                    if is_complete
                    else EventAssignmentStatus.AMBIGUOUS
                )
                assignment = EventObservationAssignment(
                    observation_key=key,
                    physical_event_id=physical_event_id,
                    status=status,
                    rationale=(
                        "All observations in the cluster satisfy the disaster "
                        "policy pairwise."
                        if len(group) > 1
                        else (
                            "No equivalent observation was found."
                            if is_complete
                            else "The observation matches multiple incompatible "
                            "cluster alternatives and was kept separate."
                        )
                    ),
                    compatible_observation_keys=tuple(sorted(compatible[key])),
                )
                assignments.append(assignment)
                if status is EventAssignmentStatus.AMBIGUOUS:
                    ambiguous_assignments.append(assignment)
            identities.append(
                PhysicalEventIdentity(
                    physical_event_id=physical_event_id,
                    event=merge(list(observations)),
                    observations=observations,
                    assignments=tuple(assignments),
                )
            )
    return PhysicalEventIdentityResult(
        physical_events=tuple(
            sorted(identities, key=lambda item: item.physical_event_id)
        ),
        ambiguous_assignments=tuple(
            sorted(ambiguous_assignments, key=lambda item: item.observation_key)
        ),
    )
