"""Deterministic, sensor-independent acquisition selection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from disaster_monitor.application.ground_imagery.temporal_policy import (
    AgeClass,
    RoleWindow,
    TemporalPlan,
    classify_freshness,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.imagery.observations import (
    Observation,
    ObservationReadiness,
    Sensor,
    TemporalRole,
    radar_comparison_compatibility,
)


class SelectionReason(StrEnum):
    """Stable reason codes for selection and availability gaps."""

    SELECTED = "selected"
    NO_ACQUISITION = "no_acquisition"
    NO_RECENT_OBSERVATION = "no_recent_observation"
    OBSCURED = "obscured"
    PARTIAL_COVERAGE = "partial_coverage"
    CATALOG_SCAN_TRUNCATED = "catalog_scan_truncated"
    QUALITY_SEARCH_INCOMPLETE = "quality_search_incomplete"
    NOT_RENDERABLE_YET = "not_renderable_yet"
    NO_COMPARABLE_BASELINE = "no_comparable_baseline"
    ONSET_UNKNOWN = "onset_unknown"


@dataclass(frozen=True, slots=True)
class GroundImagerySelection:
    """One role outcome, including an explicit missing/limited reason."""

    role: TemporalRole
    observation: Observation | None
    reason: SelectionReason
    explanation: str
    age_class: AgeClass | None = None
    alternatives: tuple[Observation, ...] = ()

    @property
    def has_observation(self) -> bool:
        return self.observation is not None


@dataclass(frozen=True, slots=True)
class SensorSelection:
    """All selected roles for one sensor, independent of the other sensor."""

    sensor: Sensor
    selections: tuple[GroundImagerySelection, ...]

    def for_role(self, role: TemporalRole | str) -> GroundImagerySelection:
        role_value = TemporalRole(role)
        for selection in self.selections:
            if selection.role is role_value:
                return selection
        raise KeyError(role_value.value)

    @property
    def has_observation(self) -> bool:
        return any(item.has_observation for item in self.selections)

    @property
    def partial_failure_reason(self) -> SelectionReason | None:
        reasons = [item.reason for item in self.selections if not item.has_observation]
        return reasons[0] if reasons else None


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Independent S1/S2 outcomes bound to one temporal plan."""

    plan: TemporalPlan
    sensors: tuple[SensorSelection, ...]

    def for_sensor(self, sensor: Sensor) -> SensorSelection:
        for selection in self.sensors:
            if selection.sensor is sensor:
                return selection
        raise KeyError(sensor.value)


def select_observations(
    plan: TemporalPlan,
    candidates_by_sensor: Mapping[Sensor, tuple[Observation, ...]],
    *,
    disaster: Disaster | None = None,
    scan_complete: Mapping[tuple[Sensor, TemporalRole], bool] | None = None,
) -> SelectionResult:
    """Select baseline/first/latest roles from bounded provider candidates.

    Candidate quality is never inferred from whole-tile cloud percentage.  A
    useful scene must carry regional quality calculated against the complete
    requested core; a missing quality record is therefore not silently useful.
    """
    selected: list[SensorSelection] = []
    for sensor in Sensor:
        candidates = _deduplicate(candidates_by_sensor.get(sensor, ()))
        roles = _roles_for_sensor(plan, sensor)
        role_results = [
            _select_role(
                plan,
                sensor,
                role,
                candidates,
                disaster=disaster,
                scan_complete=(scan_complete or {}).get((sensor, role), True),
            )
            for role in roles
        ]
        if sensor is Sensor.SENTINEL_1:
            role_results = _apply_radar_baseline_compatibility(role_results)
        selected.append(SensorSelection(sensor=sensor, selections=tuple(role_results)))
    return SelectionResult(plan=plan, sensors=tuple(selected))


def _roles_for_sensor(plan: TemporalPlan, sensor: Sensor) -> tuple[TemporalRole, ...]:
    roles = [
        role
        for role in (
            TemporalRole.PRE_EVENT_REFERENCE,
            TemporalRole.FIRST_USEFUL_AFTER_ONSET,
            TemporalRole.LATEST_USEFUL,
            TemporalRole.EARLIER_REFERENCE,
            TemporalRole.RECOVERY_CHECKPOINT,
        )
        if any(
            window.role is role and window.sensor is sensor for window in plan.windows
        )
    ]
    return tuple(roles)


def _select_role(
    plan: TemporalPlan,
    sensor: Sensor,
    role: TemporalRole,
    candidates: tuple[Observation, ...],
    *,
    disaster: Disaster | None,
    scan_complete: bool,
) -> GroundImagerySelection:
    window = plan.window_for(role, sensor=sensor)
    expanded = plan.window_for(role, sensor=sensor, expanded=True)
    in_initial = tuple(
        item for item in candidates if _in_window(item, window, role, plan)
    )
    in_expanded = tuple(
        item for item in candidates if _in_window(item, expanded, role, plan)
    )
    temporal_candidates = in_initial or in_expanded
    if not temporal_candidates:
        reason = (
            SelectionReason.CATALOG_SCAN_TRUNCATED
            if not scan_complete
            else (
                SelectionReason.ONSET_UNKNOWN
                if plan.onset is None
                and role
                in {
                    TemporalRole.LATEST_USEFUL,
                    TemporalRole.EARLIER_REFERENCE,
                }
                else SelectionReason.NO_RECENT_OBSERVATION
            )
        )
        return GroundImagerySelection(role, None, reason, _explanation(reason))

    not_renderable = tuple(
        item for item in temporal_candidates if not item.is_renderable
    )
    renderable = tuple(item for item in temporal_candidates if item.is_renderable)
    if not renderable:
        reason = (
            SelectionReason.QUALITY_SEARCH_INCOMPLETE
            if not scan_complete
            else SelectionReason.NOT_RENDERABLE_YET
        )
        return GroundImagerySelection(
            role,
            None,
            reason,
            _explanation(reason),
            alternatives=not_renderable,
        )

    with_quality = tuple(item for item in renderable if item.quality is not None)
    if not with_quality:
        reason = (
            SelectionReason.QUALITY_SEARCH_INCOMPLETE
            if not scan_complete
            else SelectionReason.OBSCURED
        )
        return GroundImagerySelection(
            role, None, reason, _explanation(reason), alternatives=renderable
        )
    useful = tuple(item for item in with_quality if _is_useful(item))
    if not useful:
        partial = tuple(item for item in with_quality if _is_partial(item))
        if not partial:
            reason = (
                SelectionReason.QUALITY_SEARCH_INCOMPLETE
                if not scan_complete
                else SelectionReason.OBSCURED
            )
            return GroundImagerySelection(
                role, None, reason, _explanation(reason), alternatives=with_quality
            )
        chosen = _rank_partial(partial, role)
        return GroundImagerySelection(
            role,
            chosen,
            SelectionReason.PARTIAL_COVERAGE,
            _explanation(SelectionReason.PARTIAL_COVERAGE),
            age_class=_age_class(chosen, plan, disaster),
            alternatives=tuple(item for item in partial if item is not chosen),
        )

    chosen = _rank_useful(useful, role, plan)
    return GroundImagerySelection(
        role,
        chosen,
        SelectionReason.SELECTED,
        _explanation(SelectionReason.SELECTED),
        age_class=_age_class(chosen, plan, disaster),
        alternatives=tuple(item for item in useful if item is not chosen),
    )


def _in_window(
    observation: Observation,
    window: RoleWindow,
    role: TemporalRole,
    plan: TemporalPlan,
) -> bool:
    capture = observation.capture
    if window.is_empty or capture.start < window.start or capture.end > window.end:
        return False
    if plan.onset is None:
        return True
    if role is TemporalRole.PRE_EVENT_REFERENCE:
        return capture.end < plan.onset.earliest
    if role is TemporalRole.FIRST_USEFUL_AFTER_ONSET:
        return capture.start >= plan.onset.latest
    if role is TemporalRole.LATEST_USEFUL:
        return capture.start >= plan.onset.latest
    return True


def _is_useful(observation: Observation) -> bool:
    quality = observation.quality
    return (
        quality is not None
        and quality.covered_fraction >= 0.95
        and quality.usable_fraction >= 0.80
        and quality.minimum_component_usable_fraction >= 0.60
    )


def _is_partial(observation: Observation) -> bool:
    quality = observation.quality
    return quality is not None and (
        quality.usable_fraction >= 0.20
        or quality.minimum_component_usable_fraction >= 0.60
    )


def _rank_useful(
    candidates: tuple[Observation, ...],
    role: TemporalRole,
    plan: TemporalPlan,
) -> Observation:
    if role is TemporalRole.LATEST_USEFUL:
        return max(
            candidates,
            key=lambda item: (
                item.capture.end,
                item.quality.minimum_component_usable_fraction,  # type: ignore[union-attr]
                item.quality.usable_fraction,  # type: ignore[union-attr]
                _stable_identity(item),
            ),
        )
    if role is TemporalRole.FIRST_USEFUL_AFTER_ONSET:
        return min(
            candidates,
            key=lambda item: (
                item.capture.start,
                -item.quality.minimum_component_usable_fraction,  # type: ignore[union-attr]
                -item.quality.usable_fraction,  # type: ignore[union-attr]
                _stable_identity(item),
            ),
        )
    if role is TemporalRole.PRE_EVENT_REFERENCE and plan.onset is not None:
        onset = plan.onset
        return min(
            candidates,
            key=lambda item: (
                onset.earliest - item.capture.end,
                -item.quality.minimum_component_usable_fraction,  # type: ignore[union-attr]
                -item.quality.usable_fraction,  # type: ignore[union-attr]
                _stable_identity(item),
            ),
        )
    return max(
        candidates,
        key=lambda item: (
            item.quality.minimum_component_usable_fraction,  # type: ignore[union-attr]
            item.quality.usable_fraction,  # type: ignore[union-attr]
            item.capture.end,
            _stable_identity(item),
        ),
    )


def _rank_partial(
    candidates: tuple[Observation, ...], role: TemporalRole
) -> Observation:
    if role is TemporalRole.FIRST_USEFUL_AFTER_ONSET:
        return min(
            candidates, key=lambda item: (item.capture.start, _stable_identity(item))
        )
    return max(
        candidates,
        key=lambda item: (
            item.capture.end,
            item.quality.minimum_component_usable_fraction,  # type: ignore[union-attr]
            item.quality.usable_fraction,  # type: ignore[union-attr]
            _stable_identity(item),
        ),
    )


def _apply_radar_baseline_compatibility(
    selections: list[GroundImagerySelection],
) -> list[GroundImagerySelection]:
    baseline = next(
        (item for item in selections if item.role is TemporalRole.PRE_EVENT_REFERENCE),
        None,
    )
    post = next(
        (
            item
            for item in selections
            if item.role
            in {TemporalRole.FIRST_USEFUL_AFTER_ONSET, TemporalRole.LATEST_USEFUL}
            and item.observation is not None
        ),
        None,
    )
    if baseline is None or post is None or baseline.observation is None:
        return selections
    compatible, _ = radar_comparison_compatibility(
        baseline.observation,
        post.observation,  # type: ignore[arg-type]
    )
    if compatible:
        return selections
    index = selections.index(baseline)
    selections[index] = GroundImagerySelection(
        role=baseline.role,
        observation=None,
        reason=SelectionReason.NO_COMPARABLE_BASELINE,
        explanation=_explanation(SelectionReason.NO_COMPARABLE_BASELINE),
        alternatives=baseline.alternatives,
    )
    return selections


def _deduplicate(candidates: tuple[Observation, ...]) -> tuple[Observation, ...]:
    by_group: dict[str, Observation] = {}
    for candidate in candidates:
        existing = by_group.get(candidate.group_key)
        if existing is None or _dedup_key(candidate) > _dedup_key(existing):
            by_group[candidate.group_key] = candidate
    return tuple(sorted(by_group.values(), key=_stable_identity))


def _dedup_key(observation: Observation) -> tuple[int, float, str, str]:
    readiness = {
        ObservationReadiness.DOWNLOADED: 4,
        ObservationReadiness.RENDERABLE: 3,
        ObservationReadiness.PROCESSING: 2,
        ObservationReadiness.CATALOGUED: 1,
        ObservationReadiness.UNAVAILABLE: 0,
    }[observation.readiness]
    quality = observation.quality.usable_fraction if observation.quality else -1.0
    return (
        readiness,
        quality,
        observation.identity.revision or "",
        _stable_identity(observation),
    )


def _stable_identity(observation: Observation) -> str:
    return observation.identity.stable_key


def _age_class(
    observation: Observation,
    plan: TemporalPlan,
    disaster: Disaster | None,
) -> AgeClass | None:
    if disaster is None:
        return None
    return classify_freshness(observation.capture, plan.reference_time, disaster)


def _explanation(reason: SelectionReason) -> str:
    return {
        SelectionReason.SELECTED: (
            "The acquisition meets the regional coverage policy."
        ),
        SelectionReason.NO_ACQUISITION: (
            "No catalog acquisition was returned for this role."
        ),
        SelectionReason.NO_RECENT_OBSERVATION: (
            "No acquisition in the permitted time window meets the role timing."
        ),
        SelectionReason.OBSCURED: (
            "Candidate acquisitions do not provide enough estimated usable core "
            "coverage."
        ),
        SelectionReason.PARTIAL_COVERAGE: (
            "A limited view is retained because it covers part of the requested scope."
        ),
        SelectionReason.CATALOG_SCAN_TRUNCATED: (
            "The catalog scan was bounded before a complete result could be "
            "established."
        ),
        SelectionReason.QUALITY_SEARCH_INCOMPLETE: (
            "Quality assessment is incomplete; this is not evidence that imagery "
            "is absent."
        ),
        SelectionReason.NOT_RENDERABLE_YET: (
            "The acquisition is catalogued but not currently renderable."
        ),
        SelectionReason.NO_COMPARABLE_BASELINE: (
            "No Sentinel-1 baseline matches the selected orbit, mode, polarization, "
            "and recipe."
        ),
        SelectionReason.ONSET_UNKNOWN: (
            "Onset is unknown, so this role is not labelled before or after impact."
        ),
    }[reason]
