"""Incident-watch aggregates, fingerprints, and canonical documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from disaster_monitor.domain.disaster_types import Disaster, ProviderTier
from disaster_monitor.domain.events import (
    EventGeometry,
    EventMeasurement,
)
from disaster_monitor.domain.evidence_types import SourceAuthority, SourceReference
from disaster_monitor.domain.incident_watch_documents import (
    _measurement_order_key,
    _require_aware,
    _source_order_key,
    _stable_physical_event_id,
    _valid_prefixed_sha256,
    canonical_hash,
    geometry_document,
    measurement_document,
    source_evidence_document,
    watch_incident_document,
)

MIN_WATCH_REFRESH_SECONDS = 300
MAX_WATCH_REFRESH_SECONDS = 86_400


class WatchScopeKind(StrEnum):
    COUNTRY = "country"
    WORLDWIDE = "worldwide"


class WatchCoverageState(StrEnum):
    EVENTS_FOUND = "events_found"
    NO_MATCHING_RECORDS = "no_matching_records"
    STALE = "stale"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class IncidentChangeKind(StrEnum):
    NEW_EVENT = "new_event"
    OBSERVATION_GAP = "observation_gap"
    MEASUREMENTS_CHANGED = "measurements_changed"
    GEOMETRY_CHANGED = "geometry_changed"
    EVIDENCE_SET_CHANGED = "evidence_set_changed"
    COVERAGE_CHANGED = "coverage_changed"


@dataclass(frozen=True, slots=True)
class IncidentWatchScope:
    kind: WatchScopeKind
    country_code: str | None = None
    country_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind is WatchScopeKind.WORLDWIDE:
            if self.country_code is not None or self.country_name is not None:
                raise ValueError("Worldwide watch scope cannot include a country.")
            return
        if (
            self.country_code is None
            or len(self.country_code) != 3
            or not self.country_code.isupper()
            or self.country_name is None
            or not self.country_name.strip()
        ):
            raise ValueError("Country watch scope requires one canonical country.")

    @classmethod
    def worldwide(cls) -> IncidentWatchScope:
        return cls(WatchScopeKind.WORLDWIDE)

    @classmethod
    def country(cls, code: str, name: str) -> IncidentWatchScope:
        return cls(WatchScopeKind.COUNTRY, code, name)

    @property
    def display_name(self) -> str:
        return self.country_name or "Worldwide"


@dataclass(frozen=True, slots=True)
class IncidentWatch:
    watch_id: str
    disaster: Disaster
    scope: IncidentWatchScope
    enabled: bool
    refresh_interval_seconds: int
    created_at: datetime
    updated_at: datetime
    next_refresh_at: datetime
    last_checked_at: datetime | None = None
    coverage_state: WatchCoverageState | None = None
    unread_change_count: int = 0

    def __post_init__(self) -> None:
        if not self.watch_id.strip():
            raise ValueError("Incident watches require a stable identifier.")
        if not isinstance(self.disaster, Disaster):
            raise TypeError("Incident watches require one supported disaster type.")
        if isinstance(self.refresh_interval_seconds, bool) or not (
            MIN_WATCH_REFRESH_SECONDS
            <= self.refresh_interval_seconds
            <= MAX_WATCH_REFRESH_SECONDS
        ):
            raise ValueError(
                "Watch refresh interval must be between 300 and 86400 seconds."
            )
        for value in (self.created_at, self.updated_at, self.next_refresh_at):
            _require_aware(value, "Incident watch times must be timezone-aware.")
        if self.last_checked_at is not None:
            _require_aware(
                self.last_checked_at,
                "Incident watch times must be timezone-aware.",
            )
        if self.unread_change_count < 0:
            raise ValueError("Unread watch change count cannot be negative.")


@dataclass(frozen=True, slots=True)
class WatchIncident:
    physical_event_id: str
    event_id: str
    disaster: Disaster
    location: str
    event_time: datetime
    geometry: EventGeometry | None
    measurements: tuple[EventMeasurement, ...]
    provider_ids: tuple[str, ...]
    provider_tier: ProviderTier
    source_authority: SourceAuthority
    source: SourceReference
    evidence_sources: tuple[SourceReference, ...]

    def __post_init__(self) -> None:
        if not self.physical_event_id.strip() or not self.event_id.strip():
            raise ValueError("Watched incidents require stable event identity.")
        if not self.location.strip():
            raise ValueError("Watched incidents require a source-backed location.")
        _require_aware(self.event_time, "Watched incident time must be timezone-aware.")
        if self.source not in self.evidence_sources:
            raise ValueError(
                "Watched incident evidence must include its primary source."
            )

    @classmethod
    def from_source_evidence(
        cls,
        *,
        event_id: str,
        disaster: Disaster,
        location: str,
        event_time: datetime,
        geometry: EventGeometry | None,
        measurements: tuple[EventMeasurement, ...],
        provider_ids: tuple[str, ...],
        provider_tier: ProviderTier,
        source_authority: SourceAuthority,
        source: SourceReference,
        evidence_sources: tuple[SourceReference, ...],
        physical_event_id: str | None = None,
    ) -> WatchIncident:
        sources = {
            source,
            *(item.source for item in measurements),
            *((geometry.source,) if geometry is not None else ()),
            *evidence_sources,
        }
        ordered_sources = tuple(sorted(sources, key=_source_order_key))
        stable_id = physical_event_id or _stable_physical_event_id(
            disaster, source.source_id, event_id
        )
        return cls(
            physical_event_id=stable_id,
            event_id=event_id,
            disaster=disaster,
            location=location,
            event_time=event_time,
            geometry=geometry,
            measurements=tuple(sorted(measurements, key=_measurement_order_key)),
            provider_ids=tuple(sorted(set(provider_ids))),
            provider_tier=provider_tier,
            source_authority=source_authority,
            source=source,
            evidence_sources=ordered_sources,
        )

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.source_id for item in self.evidence_sources}))

    @property
    def geometry_hash(self) -> str:
        return canonical_hash(geometry_document(self.geometry))

    @property
    def measurements_hash(self) -> str:
        return canonical_hash(
            [measurement_document(item) for item in self.measurements]
        )

    @property
    def evidence_hash(self) -> str:
        return canonical_hash(
            {
                "provider_ids": self.provider_ids,
                "sources": [
                    source_evidence_document(item) for item in self.evidence_sources
                ],
            }
        )

    @property
    def state_hash(self) -> str:
        return canonical_hash(watch_incident_document(self))


@dataclass(frozen=True, slots=True)
class IncidentWatchObservation:
    observation_id: str
    watch_id: str
    observed_at: datetime
    coverage_state: WatchCoverageState
    incidents: tuple[WatchIncident, ...]
    provider_names: tuple[str, ...]
    warnings: tuple[str, ...]
    state_hash: str
    successful: bool
    retryable: bool = False
    provider_source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.watch_id.strip():
            raise ValueError("Watch observations require stable identity.")
        _require_aware(
            self.observed_at, "Watch observation time must be timezone-aware."
        )
        if not _valid_prefixed_sha256(self.state_hash):
            raise ValueError("Watch observation state must have a SHA-256 identity.")

    @classmethod
    def create(
        cls,
        *,
        watch_id: str,
        observed_at: datetime,
        coverage_state: WatchCoverageState,
        incidents: tuple[WatchIncident, ...],
        provider_names: tuple[str, ...],
        warnings: tuple[str, ...],
        successful: bool,
        retryable: bool = False,
        provider_source_ids: tuple[str, ...] = (),
    ) -> IncidentWatchObservation:
        ordered_incidents = tuple(
            sorted(
                incidents,
                key=lambda item: (
                    item.physical_event_id,
                    item.event_time,
                    item.event_id,
                ),
            )
        )
        document = {
            "coverage_state": coverage_state.value,
            "incidents": [watch_incident_document(item) for item in ordered_incidents],
            "provider_names": sorted(set(provider_names)),
            "provider_source_ids": sorted(set(provider_source_ids)),
            "successful": successful,
            "retryable": retryable,
        }
        state_hash = canonical_hash(document)
        return cls(
            observation_id=(
                "incident-watch-observation:"
                + hashlib.sha256(f"{watch_id}|{state_hash}".encode()).hexdigest()[:24]
            ),
            watch_id=watch_id,
            observed_at=observed_at,
            coverage_state=coverage_state,
            incidents=ordered_incidents,
            provider_names=tuple(sorted(set(provider_names))),
            warnings=tuple(dict.fromkeys(warnings)),
            state_hash=state_hash,
            successful=successful,
            retryable=retryable,
            provider_source_ids=tuple(sorted(set(provider_source_ids))),
        )


@dataclass(frozen=True, slots=True)
class IncidentWatchChange:
    change_id: str
    watch_id: str
    kind: IncidentChangeKind
    summary: str
    detail: str
    created_at: datetime
    source_ids: tuple[str, ...]
    observation_id: str
    previous_observation_id: str | None
    before_hash: str | None
    after_hash: str | None
    incident: WatchIncident | None = None
    read_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.change_id.strip() or not self.watch_id.strip():
            raise ValueError("Watch changes require stable identity.")
        if not self.summary.strip() or not self.detail.strip():
            raise ValueError("Watch changes require an auditable description.")
        _require_aware(self.created_at, "Watch change time must be timezone-aware.")
        if self.read_at is not None:
            _require_aware(self.read_at, "Watch read time must be timezone-aware.")

    @classmethod
    def create(
        cls,
        *,
        watch: IncidentWatch,
        kind: IncidentChangeKind,
        current: IncidentWatchObservation,
        previous: IncidentWatchObservation | None,
        summary: str,
        detail: str,
        incident: WatchIncident | None,
        before_hash: str | None,
        after_hash: str | None,
        source_ids: tuple[str, ...],
    ) -> IncidentWatchChange:
        physical_event_id = incident.physical_event_id if incident is not None else ""
        material = "|".join(
            (
                watch.watch_id,
                kind.value,
                previous.observation_id if previous is not None else "",
                current.observation_id,
                current.observed_at.isoformat(),
                physical_event_id,
                before_hash or "",
                after_hash or "",
            )
        )
        return cls(
            change_id=(
                "incident-watch-change:"
                + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
            ),
            watch_id=watch.watch_id,
            kind=kind,
            summary=summary,
            detail=detail,
            created_at=current.observed_at,
            source_ids=tuple(sorted(set(source_ids))),
            observation_id=current.observation_id,
            previous_observation_id=(
                previous.observation_id if previous is not None else None
            ),
            before_hash=before_hash,
            after_hash=after_hash,
            incident=incident,
        )

    @classmethod
    def create_coverage_change(
        cls,
        *,
        watch: IncidentWatch,
        previous: IncidentWatchObservation | None,
        current: IncidentWatchObservation,
    ) -> IncidentWatchChange:
        previous_label = (
            previous.coverage_state.value if previous is not None else "not_checked"
        )
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for observation in (previous, current)
                    if observation is not None
                    for source_id in observation.provider_source_ids
                }
                | {
                    source_id
                    for observation in (previous, current)
                    if observation is not None
                    for incident in observation.incidents
                    for source_id in incident.source_ids
                }
            )
        )
        return cls.create(
            watch=watch,
            kind=IncidentChangeKind.COVERAGE_CHANGED,
            current=current,
            previous=previous,
            summary="Watch coverage changed",
            detail=(
                f"Bounded provider coverage changed from {previous_label} to "
                f"{current.coverage_state.value}."
            ),
            incident=None,
            before_hash=(
                canonical_hash(previous_label) if previous is not None else None
            ),
            after_hash=canonical_hash(current.coverage_state.value),
            source_ids=source_ids,
        )

    def mark_read(self, read_at: datetime) -> IncidentWatchChange:
        return replace(self, read_at=read_at)
