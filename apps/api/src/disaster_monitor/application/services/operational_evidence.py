"""Persist normalized evidence only when immutable source lineage is complete."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.domain.disaster import (
    EventGeometry,
    EventGeometryKind,
    EvidenceObservation,
    EvidenceWorldState,
)
from disaster_monitor.domain.operations import (
    EventObservationLinkRecord,
    NormalizedObservationRecord,
    PhysicalEventRecord,
    WorldStateVersionRecord,
)

PARSER_VERSION = "evidence-state.v1"
POLICY_VERSION = "evidence-world-state.v1"


@dataclass(frozen=True, slots=True)
class OperationalEvidenceResult:
    """Outcome of the fail-closed durable lineage gate."""

    persisted: bool
    observation_count: int
    missing_snapshot_observation_ids: tuple[str, ...] = ()


class OperationalEvidenceRecorder:
    """Project canonical evidence into append-only operational records."""

    def __init__(self, repository: OperationalRepository) -> None:
        self._repository = repository

    async def record(self, state: EvidenceWorldState) -> OperationalEvidenceResult:
        observations = _observations(state)
        missing = [
            item.observation_id
            for item in observations
            if item.fact.source.snapshot_id is None
        ]
        if state.physical_event.event.source.snapshot_id is None:
            missing.append(f"event:{state.physical_event.event.event_id}")
        if missing:
            return OperationalEvidenceResult(False, 0, tuple(missing))

        records = (
            _event_observation_record(state),
            *(tuple(_observation_record(item) for item in observations)),
        )
        event = state.physical_event.event
        await self._repository.append_physical_event(
            PhysicalEventRecord(
                physical_event_id=state.physical_event.physical_event_id,
                hazard=event.hazard.value,
                country_code=event.country.alpha3_code,
                latitude=(
                    event.geometry.coordinates[0].latitude
                    if event.geometry is not None
                    and event.geometry.kind is EventGeometryKind.POINT
                    else None
                ),
                longitude=(
                    event.geometry.coordinates[0].longitude
                    if event.geometry is not None
                    and event.geometry.kind is EventGeometryKind.POINT
                    else None
                ),
                created_at=state.evaluated_at,
            )
        )
        await self._repository.append_observations(records)
        await self._repository.append_event_links(
            tuple(
                EventObservationLinkRecord(
                    physical_event_id=state.physical_event.physical_event_id,
                    observation_id=item.observation_id,
                    assignment_status="matched",
                    rationale=(
                        "Normalized report evidence retained for the selected "
                        "physical event under evidence-state.v1."
                    ),
                )
                for item in records
            )
        )
        canonical_state = _canonical_state(state)
        snapshot_ids = sorted({item.snapshot_id for item in records})
        world_record = WorldStateVersionRecord(
            state_version=state.state_version,
            physical_event_id=state.physical_event.physical_event_id,
            source_set_sha256=_sha256({"snapshot_ids": snapshot_ids}),
            canonical_state_sha256=_sha256(canonical_state),
            policy_version=POLICY_VERSION,
            created_at=state.evaluated_at,
        )
        await self._repository.append_world_state(world_record)
        return OperationalEvidenceResult(True, len(records))


def _observations(state: EvidenceWorldState) -> tuple[EvidenceObservation, ...]:
    unique: dict[str, EvidenceObservation] = {}
    for claim in state.claims:
        for history in claim.history:
            unique[history.observation.observation_id] = history.observation
    return tuple(unique[key] for key in sorted(unique))


def _observation_record(item: EvidenceObservation) -> NormalizedObservationRecord:
    snapshot_id = item.fact.source.snapshot_id
    if snapshot_id is None:
        raise ValueError("A normalized observation requires an immutable snapshot.")
    return NormalizedObservationRecord(
        observation_id=item.observation_id,
        snapshot_id=snapshot_id,
        source_id=item.fact.source.source_id,
        observation_type=item.fact.category,
        effective_at=item.chronology.effective_at,
        parser_version=PARSER_VERSION,
        canonical_json=_json(_observation_document(item)),
    )


def _event_observation_record(
    state: EvidenceWorldState,
) -> NormalizedObservationRecord:
    event = state.physical_event.event
    snapshot_id = event.source.snapshot_id
    if snapshot_id is None:
        raise ValueError("A normalized event requires an immutable snapshot.")
    document = {
        "schema_version": "dm.normalized-event-observation.v1",
        "physical_event_id": state.physical_event.physical_event_id,
        "event_id": event.event_id,
        "provider_ids": sorted(event.provider_ids),
        "hazard": event.hazard.value,
        "country_code": event.country.alpha3_code,
        "location": event.location,
        "event_time": _time(event.event_time),
        "geometry": _geometry_document(event.geometry),
        "measurements": [
            {"name": item.name, "value": item.value, "unit": item.unit}
            for item in event.measurements
        ],
        "source": {
            "source_id": event.source.source_id,
            "snapshot_id": snapshot_id,
            "canonical_url": event.source.canonical_url,
            "authority": event.source.authority.value,
        },
        "parser_version": PARSER_VERSION,
    }
    digest = hashlib.sha256(_json(document).encode("utf-8")).hexdigest()[:24]
    return NormalizedObservationRecord(
        observation_id=f"event-observation:{digest}",
        snapshot_id=snapshot_id,
        source_id=event.source.source_id,
        observation_type="disaster_event",
        effective_at=event.event_time,
        parser_version=PARSER_VERSION,
        canonical_json=_json(document),
    )


def _geometry_document(geometry: EventGeometry | None) -> dict[str, Any] | None:
    if geometry is None:
        return None
    return {
        "kind": geometry.kind.value,
        "coordinates": [
            {"latitude": point.latitude, "longitude": point.longitude}
            for point in geometry.coordinates
        ],
        "description": geometry.description,
        "source_id": geometry.source.source_id,
    }


def _observation_document(item: EvidenceObservation) -> dict[str, Any]:
    source = item.fact.source
    return {
        "schema_version": "dm.normalized-observation.v1",
        "observation_id": item.observation_id,
        "claim_key": item.claim_key,
        "fact": {
            "category": item.fact.category,
            "label": item.fact.label,
            "value": item.fact.value,
            "status": item.fact.status.value,
            "event_id": item.fact.event_id,
            "claim_id": item.fact.claim_id,
        },
        "source": {
            "source_id": source.source_id,
            "snapshot_id": source.snapshot_id,
            "canonical_url": source.canonical_url,
            "authority": source.authority.value,
        },
        "chronology": {
            "observed_at": _time(item.chronology.observed_at),
            "published_at": _time(item.chronology.published_at),
            "updated_at": _time(item.chronology.updated_at),
            "retrieved_at": _time(item.chronology.retrieved_at),
            "effective_at": _time(item.chronology.effective_at),
        },
        "report": {
            "canonical_url": item.report.source.canonical_url,
            "event_id": item.report.event_id,
            "correlation": (
                item.report.correlation.value if item.report.correlation else None
            ),
        },
        "parser_version": PARSER_VERSION,
    }


def _canonical_state(state: EvidenceWorldState) -> dict[str, Any]:
    return {
        "schema_version": "dm.evidence-world-state.v1",
        "state_version": state.state_version,
        "physical_event_id": state.physical_event.physical_event_id,
        "evaluated_at": _time(state.evaluated_at),
        "claims": [
            {
                "claim_key": claim.claim_key,
                "availability": claim.availability.value,
                "current_observation_id": (
                    claim.current.observation_id if claim.current else None
                ),
                "history": [
                    {
                        "observation_id": history.observation.observation_id,
                        "disposition": history.disposition.value,
                        "freshness": history.freshness.value,
                        "rule_id": history.rule_id,
                    }
                    for history in claim.history
                ],
                "omission_snapshot_ids": sorted(
                    source.snapshot_id
                    for source in claim.omission_reports
                    if source.snapshot_id is not None
                ),
            }
            for claim in state.claims
        ],
        "policy_version": POLICY_VERSION,
    }


def _time(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def _json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()
