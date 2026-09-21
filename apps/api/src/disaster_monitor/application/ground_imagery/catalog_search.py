"""Bounded, sensor-independent catalog search orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.application.ground_imagery.models import SensorSearchStatus
from disaster_monitor.application.ground_imagery.temporal_policy import (
    RoleWindow,
    TemporalPlan,
)
from disaster_monitor.application.ports.ground_imagery.catalog import (
    CatalogSearchError,
    GroundImageryCatalog,
    GroundImageryCatalogQuery,
)
from disaster_monitor.domain.imagery.observations import (
    ImpactOnset,
    Observation,
    ObservationReadiness,
    Sensor,
    TemporalRole,
)
from disaster_monitor.domain.imagery.regions import MultiPolygon


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    """Candidates and per-sensor scan state from one bounded search."""

    candidates: Mapping[Sensor, tuple[Observation, ...]]
    statuses: tuple[SensorSearchStatus, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SensorSearchResult:
    sensor: Sensor
    observations: tuple[Observation, ...]
    scanned_count: int
    scan_complete: bool
    next_cursor: str | None
    failure: tuple[str, str] | None


class GroundImageryCatalogSearcher:
    """Search each sensor and temporal role under one global item budget."""

    def __init__(
        self, catalog: GroundImageryCatalog, *, maximum_catalog_items: int
    ) -> None:
        if not 1 <= maximum_catalog_items <= 500:
            raise ValueError(
                "The imagery catalog scan budget must be between 1 and 500."
            )
        self._catalog = catalog
        self._maximum_catalog_items = maximum_catalog_items

    async def search(
        self,
        geometry: MultiPolygon,
        plan: TemporalPlan,
        sensors: tuple[Sensor, ...],
    ) -> CatalogSearchResult:
        sensor_results = await asyncio.gather(
            *(self._search_sensor(geometry, plan, sensor) for sensor in sensors)
        )
        results = {result.sensor: result for result in sensor_results}

        statuses = tuple(
            _search_status(
                sensor=sensor,
                scanned_count=results[sensor].scanned_count,
                scan_complete=results[sensor].scan_complete,
                next_cursor=results[sensor].next_cursor,
                failure=results[sensor].failure,
            )
            for sensor in sensors
        )
        return CatalogSearchResult(
            candidates={
                sensor: tuple(_dedup_observations(list(results[sensor].observations)))
                for sensor in sensors
            },
            statuses=statuses,
            reason_codes=tuple(
                result.failure[0]
                for result in sensor_results
                if result.failure is not None
            ),
        )

    async def _search_sensor(
        self,
        geometry: MultiPolygon,
        plan: TemporalPlan,
        sensor: Sensor,
    ) -> _SensorSearchResult:
        observations: list[Observation] = []
        scanned = 0
        complete = True
        cursor: str | None = None
        failure: tuple[str, str] | None = None

        for role in _roles_for(plan, sensor):
            window = plan.window_for(role, sensor=sensor)
            if window.is_empty:
                continue
            (
                window_observations,
                count,
                is_complete,
                cursor,
                window_failure,
            ) = await self._scan_window(
                geometry,
                sensor,
                role,
                window.start,
                window.end,
                scanned,
            )
            observations.extend(window_observations)
            scanned = min(self._maximum_catalog_items, scanned + count)
            complete = complete and is_complete
            if window_failure is not None:
                failure = window_failure
                break

            if not _needs_window_expansion(plan, role, window_observations):
                continue
            expanded = plan.window_for(role, sensor=sensor, expanded=True)
            if expanded.is_empty or (expanded.start, expanded.end) == (
                window.start,
                window.end,
            ):
                continue
            (
                extra,
                extra_count,
                extra_complete,
                cursor,
                window_failure,
            ) = await self._scan_window(
                geometry,
                sensor,
                role,
                expanded.start,
                expanded.end,
                scanned,
            )
            observations.extend(extra)
            scanned = min(self._maximum_catalog_items, scanned + extra_count)
            complete = complete and extra_complete
            if window_failure is not None:
                failure = window_failure
                break

        return _SensorSearchResult(
            sensor=sensor,
            observations=tuple(observations),
            scanned_count=scanned,
            scan_complete=complete,
            next_cursor=cursor,
            failure=failure,
        )

    async def _scan_window(
        self,
        geometry: MultiPolygon,
        sensor: Sensor,
        role: TemporalRole,
        start: datetime,
        end: datetime,
        already_scanned: int,
    ) -> tuple[
        tuple[Observation, ...],
        int,
        bool,
        str | None,
        tuple[str, str] | None,
    ]:
        observations: list[Observation] = []
        scanned = 0
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            remaining = self._maximum_catalog_items - already_scanned - scanned
            if remaining < 1:
                return tuple(observations), scanned, False, cursor, None
            query = GroundImageryCatalogQuery(
                sensor=sensor,
                geometry=geometry,
                start=start,
                end=end,
                role=role,
                limit=min(100, remaining),
                cursor=cursor,
            )
            try:
                page = await self._catalog.search(query)
            except CatalogSearchError as error:
                return (
                    tuple(observations),
                    scanned,
                    False,
                    cursor,
                    (error.reason_code, str(error)),
                )
            observations.extend(page.observations)
            scanned += max(page.scanned_count, len(page.observations))
            if page.next_cursor is None:
                return tuple(observations), scanned, page.scan_complete, None, None
            if page.next_cursor in seen_cursors:
                return (
                    tuple(observations),
                    scanned,
                    False,
                    page.next_cursor,
                    (
                        "catalog_cursor_loop",
                        "The CDSE catalog returned a repeated pagination cursor.",
                    ),
                )
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor


def _search_status(
    *,
    sensor: Sensor,
    scanned_count: int,
    scan_complete: bool,
    next_cursor: str | None,
    failure: tuple[str, str] | None,
) -> SensorSearchStatus:
    return SensorSearchStatus(
        sensor=sensor,
        scanned_count=scanned_count,
        scan_complete=scan_complete,
        next_cursor=next_cursor,
        failure_code=None if failure is None else failure[0],
        failure_detail=None if failure is None else failure[1],
    )


def _roles_for(plan: TemporalPlan, sensor: Sensor) -> tuple[TemporalRole, ...]:
    return tuple(
        role
        for role in TemporalRole
        if any(item.role is role and item.sensor is sensor for item in plan.windows)
    )


def _needs_window_expansion(
    plan: TemporalPlan, role: TemporalRole, observations: tuple[Observation, ...]
) -> bool:
    """Expand only when the initial search has no full-quality candidate."""
    if not observations:
        return True
    sensor = observations[0].sensor
    window = plan.window_for(role, sensor=sensor)
    for observation in observations:
        if not _capture_in_window(observation, window, role, plan.onset):
            continue
        quality = observation.quality
        if (
            observation.readiness
            in {ObservationReadiness.RENDERABLE, ObservationReadiness.DOWNLOADED}
            and quality is not None
            and quality.covered_fraction >= 0.95
            and quality.usable_fraction >= 0.80
            and quality.minimum_component_usable_fraction >= 0.60
        ):
            return False
    return True


def _capture_in_window(
    observation: Observation,
    window: RoleWindow,
    role: TemporalRole,
    onset: ImpactOnset | None,
) -> bool:
    if window.is_empty:
        return False
    if observation.capture.start < window.start or observation.capture.end > window.end:
        return False
    if onset is None:
        return True
    if role is TemporalRole.PRE_EVENT_REFERENCE:
        return observation.capture.end < onset.earliest
    if role in {
        TemporalRole.FIRST_USEFUL_AFTER_ONSET,
        TemporalRole.LATEST_USEFUL,
    }:
        return observation.capture.start >= onset.latest
    return True


def _dedup_observations(items: list[Observation]) -> list[Observation]:
    selected: dict[str, Observation] = {}
    for item in items:
        key = item.group_key
        current = selected.get(key)
        if current is None or (
            item.is_renderable,
            item.quality.usable_fraction if item.quality else -1,
            item.identity.revision or "",
        ) > (
            current.is_renderable,
            current.quality.usable_fraction if current.quality else -1,
            current.identity.revision or "",
        ):
            selected[key] = item
    return sorted(selected.values(), key=lambda item: item.identity.stable_key)


__all__ = ["CatalogSearchResult", "GroundImageryCatalogSearcher"]
