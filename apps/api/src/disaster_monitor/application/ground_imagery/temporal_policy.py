"""Versioned time windows and freshness language for ground imagery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from disaster_monitor.domain.disaster import Disaster, IncidentActivityStatus
from disaster_monitor.domain.imagery.observations import (
    CaptureInterval,
    ImpactOnset,
    OnsetPrecision,
    Sensor,
    TemporalRole,
)

__all__ = [
    "AgeClass",
    "CaptureRelation",
    "ImpactOnset",
    "OnsetPrecision",
    "POLICY_VERSION",
    "RoleWindow",
    "TemporalPlan",
    "build_temporal_plan",
    "capture_delay_range",
    "classify_capture",
    "classify_freshness",
    "watch_check_interval",
]

POLICY_VERSION = "sentinel-ground-view-v1"


class AgeClass(StrEnum):
    """Operator-facing freshness class, always accompanied by exact age."""

    RECENT = "recent"
    AGING = "aging"
    OLDER_CONTEXT = "older_context"
    HISTORICAL = "historical"


class CaptureRelation(StrEnum):
    """Temporal relation to the bounded onset interval."""

    DEFINITELY_PRE_EVENT = "definitely_pre_event"
    DEFINITELY_AFTER_ONSET = "definitely_after_onset"
    ONSET_OVERLAP_OR_UNCERTAIN = "onset_overlap_or_uncertain"
    ONSET_UNKNOWN = "onset_unknown"


@dataclass(frozen=True, slots=True)
class RoleWindow:
    """Initial and bounded expansion window for one sensor role."""

    role: TemporalRole
    sensor: Sensor
    start: datetime
    end: datetime
    expanded_start: datetime
    expanded_end: datetime

    def __post_init__(self) -> None:
        timestamps = (
            self.start,
            self.end,
            self.expanded_start,
            self.expanded_end,
        )
        if any(
            value.tzinfo is None or value.utcoffset() is None for value in timestamps
        ):
            raise ValueError("Imagery role windows must use timezone-aware timestamps.")
        if self.expanded_start > self.start or self.expanded_end < self.end:
            raise ValueError(
                "An expanded imagery window must contain its initial window."
            )

    @property
    def is_empty(self) -> bool:
        return self.end < self.start


@dataclass(frozen=True, slots=True)
class TemporalPlan:
    """Immutable temporal plan bound to a reference time and policy version."""

    reference_time: datetime
    onset: ImpactOnset | None
    impact_end: datetime | None
    policy_version: str
    windows: tuple[RoleWindow, ...]
    recovery_anchor: datetime | None = None

    def __post_init__(self) -> None:
        if (
            self.reference_time.tzinfo is None
            or self.reference_time.utcoffset() is None
        ):
            raise ValueError("The imagery reference time must be timezone-aware.")
        if self.impact_end is not None and (
            self.impact_end.tzinfo is None or self.impact_end.utcoffset() is None
        ):
            raise ValueError("The imagery impact end must be timezone-aware.")
        if not self.policy_version.strip():
            raise ValueError("A temporal plan requires a policy version.")

    def window_for(
        self,
        role: TemporalRole,
        *,
        sensor: Sensor | None = None,
        expanded: bool = False,
    ) -> RoleWindow:
        matches = [
            window
            for window in self.windows
            if window.role is role and (sensor is None or window.sensor is sensor)
        ]
        if not matches:
            raise KeyError(f"No temporal window exists for {role.value}.")
        window = matches[0]
        if not expanded:
            return window
        return RoleWindow(
            role=window.role,
            sensor=window.sensor,
            start=window.expanded_start,
            end=window.expanded_end,
            expanded_start=window.expanded_start,
            expanded_end=window.expanded_end,
        )

    def label_for(self, role: TemporalRole) -> str:
        if self.onset is None and role in {
            TemporalRole.LATEST_USEFUL,
            TemporalRole.EARLIER_REFERENCE,
        }:
            return (
                "Latest observation"
                if role is TemporalRole.LATEST_USEFUL
                else "Earlier observation"
            )
        return {
            TemporalRole.PRE_EVENT_REFERENCE: "Before event",
            TemporalRole.FIRST_USEFUL_AFTER_ONSET: "First observation after impact",
            TemporalRole.LATEST_USEFUL: "Latest useful observation",
            TemporalRole.EARLIER_REFERENCE: "Earlier observation",
            TemporalRole.RECOVERY_CHECKPOINT: "Recovery checkpoint",
        }[role]


def build_temporal_plan(
    *,
    onset: ImpactOnset | None,
    reference_time: datetime,
    disaster: Disaster,
    activity_status: IncidentActivityStatus = IncidentActivityStatus.UNKNOWN,
    impact_end: datetime | None = None,
    recovery_anchor: datetime | None = None,
    policy_version: str = POLICY_VERSION,
) -> TemporalPlan:
    """Build bounded S1/S2 windows without using publication timestamps."""
    _require_aware(reference_time, "reference_time")
    if impact_end is not None:
        _require_aware(impact_end, "impact_end")
    if recovery_anchor is not None:
        _require_aware(recovery_anchor, "recovery_anchor")
    windows: list[RoleWindow] = []

    if onset is not None:
        for sensor, initial_days, expanded_days in (
            (Sensor.SENTINEL_2, 30, 90),
            (Sensor.SENTINEL_1, 24, 72),
        ):
            windows.append(
                RoleWindow(
                    TemporalRole.PRE_EVENT_REFERENCE,
                    sensor,
                    onset.earliest - timedelta(days=initial_days),
                    onset.earliest,
                    onset.earliest - timedelta(days=expanded_days),
                    onset.earliest,
                )
            )
        first_start = onset.latest
        windows.extend(
            RoleWindow(
                TemporalRole.FIRST_USEFUL_AFTER_ONSET,
                sensor,
                first_start,
                min(first_start + timedelta(days=14), reference_time),
                first_start,
                min(first_start + timedelta(days=30), reference_time),
            )
            for sensor in Sensor
        )
        for sensor in Sensor:
            windows.append(
                RoleWindow(
                    TemporalRole.LATEST_USEFUL,
                    sensor,
                    max(reference_time - timedelta(days=14), onset.latest),
                    reference_time,
                    max(reference_time - timedelta(days=30), onset.latest),
                    reference_time,
                )
            )
    else:
        for sensor in Sensor:
            latest_start = reference_time - timedelta(days=14)
            windows.extend(
                (
                    RoleWindow(
                        TemporalRole.LATEST_USEFUL,
                        sensor,
                        latest_start,
                        reference_time,
                        reference_time - timedelta(days=30),
                        reference_time,
                    ),
                    RoleWindow(
                        TemporalRole.EARLIER_REFERENCE,
                        sensor,
                        reference_time - timedelta(days=44),
                        latest_start,
                        reference_time - timedelta(days=74),
                        latest_start,
                    ),
                )
            )

    if (impact_end is not None or recovery_anchor is not None) and onset is not None:
        anchor = recovery_anchor or impact_end
        assert anchor is not None
        for sensor in Sensor:
            start = max(anchor - timedelta(days=3), onset.latest)
            end = min(anchor + timedelta(days=3), reference_time)
            windows.append(
                RoleWindow(
                    TemporalRole.RECOVERY_CHECKPOINT,
                    sensor,
                    start,
                    end,
                    start,
                    end,
                )
            )

    return TemporalPlan(
        reference_time=reference_time,
        onset=onset,
        impact_end=impact_end,
        policy_version=policy_version,
        windows=tuple(windows),
        recovery_anchor=recovery_anchor or impact_end,
    )


def classify_capture(
    capture: CaptureInterval, onset: ImpactOnset | None
) -> CaptureRelation:
    if onset is None:
        return CaptureRelation.ONSET_UNKNOWN
    if capture.end < onset.earliest:
        return CaptureRelation.DEFINITELY_PRE_EVENT
    if capture.start >= onset.latest:
        return CaptureRelation.DEFINITELY_AFTER_ONSET
    return CaptureRelation.ONSET_OVERLAP_OR_UNCERTAIN


def classify_freshness(
    capture: CaptureInterval,
    reference_time: datetime,
    disaster: Disaster,
) -> AgeClass:
    """Classify age using capture end, not provider publication or retrieval."""
    _require_aware(reference_time, "reference_time")
    age = reference_time - capture.end
    if age < timedelta(0):
        return AgeClass.HISTORICAL
    if disaster in {
        Disaster.FLOOD,
        Disaster.WILDFIRE,
        Disaster.TROPICAL_CYCLONE,
        Disaster.VOLCANIC_ERUPTION,
    }:
        if age <= timedelta(hours=48):
            return AgeClass.RECENT
        if age <= timedelta(days=7):
            return AgeClass.AGING
    else:
        if age <= timedelta(days=7):
            return AgeClass.RECENT
        if age <= timedelta(days=30):
            return AgeClass.AGING
    return AgeClass.OLDER_CONTEXT


def capture_delay_range(
    capture: CaptureInterval, onset: ImpactOnset | None
) -> tuple[timedelta, timedelta] | None:
    """Return conservative onset-to-capture delay bounds for first-look copy."""
    if onset is None:
        return None
    return capture.start - onset.latest, capture.end - onset.earliest


def watch_check_interval(
    created_at: datetime,
    now: datetime,
    source_reported_ended: bool = False,
) -> timedelta | None:
    """Return the policy cadence, or ``None`` after the ended-event stop date."""
    _require_aware(created_at, "created_at")
    _require_aware(now, "now")
    elapsed = now - created_at
    if elapsed < timedelta(0):
        raise ValueError("A watch cannot be checked before it was created.")
    if source_reported_ended:
        return timedelta(hours=24) if elapsed <= timedelta(days=30) else None
    if elapsed <= timedelta(hours=72):
        return timedelta(hours=1)
    if elapsed <= timedelta(days=14):
        return timedelta(hours=3)
    if elapsed <= timedelta(days=30):
        return timedelta(hours=12)
    return timedelta(hours=24)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")
