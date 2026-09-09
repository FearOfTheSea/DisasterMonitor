"""Stable JSON encoding for the durable worldwide incident projection."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from disaster_monitor.application.evidence.event_policies import (
    CompoundHazardCorrelation,
    CompoundHazardRelationship,
)
from disaster_monitor.application.incidents.country_association import (
    CountryAssociationBasis,
    IncidentCountryAssociation,
)
from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsSnapshot,
    DisasterIncidentCoverage,
    IncidentCoverageState,
)
from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionRecord,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    IncidentActivityStatus,
    ObservationKind,
    ProviderTier,
    SourceAuthority,
    geometry_from_document,
    measurement_from_document,
    source_from_document,
)
from disaster_monitor.domain.incident_watch_documents import (
    geometry_document,
    measurement_document,
    source_document,
)
from disaster_monitor.domain.news import (
    IncidentCandidateStatus,
    IncidentDetectionTimeline,
)


def snapshot_to_projection(
    snapshot: ActiveIncidentsSnapshot, *, created_at: datetime
) -> IncidentProjectionRecord:
    version = snapshot.snapshot_version
    if version is None:
        raise ValueError("A durable incident projection requires a snapshot version.")
    payload = {
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "incidents": [_incident_document(item) for item in snapshot.incidents],
        "observations": [_incident_document(item) for item in snapshot.observations],
        "coverage": [_coverage_document(item) for item in snapshot.coverage],
        "warnings": list(snapshot.warnings),
        "correlations": [_correlation_document(item) for item in snapshot.correlations],
        "snapshot_version": version,
        "total_incident_count": snapshot.total_incident_count,
    }
    return IncidentProjectionRecord(
        projection_id=version,
        snapshot_version=version,
        retrieved_at=snapshot.retrieved_at,
        created_at=created_at,
        payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )


def projection_to_snapshot(
    projection: IncidentProjectionRecord,
) -> ActiveIncidentsSnapshot:
    try:
        payload = _mapping(json.loads(projection.payload_json))
        incidents = tuple(
            _incident_from_document(item) for item in _list(payload, "incidents")
        )
        observations = tuple(
            _incident_from_document(item) for item in _list(payload, "observations")
        )
        coverage = tuple(
            _coverage_from_document(item) for item in _list(payload, "coverage")
        )
        correlations = tuple(
            _correlation_from_document(item) for item in _list(payload, "correlations")
        )
        version = str(payload["snapshot_version"])
        if version != projection.snapshot_version:
            raise ValueError("Projection payload and row versions differ.")
        total = payload.get("total_incident_count")
        return ActiveIncidentsSnapshot(
            retrieved_at=datetime.fromisoformat(str(payload["retrieved_at"])),
            incidents=incidents,
            observations=observations,
            coverage=coverage,
            warnings=tuple(str(item) for item in _list(payload, "warnings")),
            correlations=correlations,
            snapshot_version=version,
            total_incident_count=(int(total) if total is not None else None),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("The durable incident projection is invalid.") from error


def _incident_document(value: ActiveIncident) -> dict[str, object]:
    return {
        "event_id": value.event_id,
        "physical_event_id": value.physical_event_id,
        "disaster": value.disaster.value,
        "country": (
            {
                "country_code": value.country.country_code,
                "country_name": value.country.country_name,
                "basis": value.country.basis.value,
                "distance_km": value.country.distance_km,
            }
            if value.country is not None
            else None
        ),
        "location": value.location,
        "event_time": value.event_time.isoformat(),
        "geometry": geometry_document(value.geometry),
        "measurements": [measurement_document(item) for item in value.measurements],
        "provider_ids": list(value.provider_ids),
        "lineage_ids": list(value.lineage_ids),
        "provider_tier": value.provider_tier.value,
        "source_authority": value.source_authority.value,
        "source": source_document(value.source),
        "evidence_sources": [source_document(item) for item in value.evidence_sources],
        "observation_kind": value.observation_kind.value,
        "activity_status": value.activity_status.value,
        "verification_status": value.verification_status.value,
        "detection": {
            "news_break_at": _optional_time(value.detection.news_break_at),
            "first_observed_at": _optional_time(value.detection.first_observed_at),
            "candidate_created_at": _optional_time(
                value.detection.candidate_created_at
            ),
            "verified_at": _optional_time(value.detection.verified_at),
            "monitor_visible_at": _optional_time(value.detection.monitor_visible_at),
            "assistant_ready_at": _optional_time(value.detection.assistant_ready_at),
        },
    }


def _incident_from_document(value: object) -> ActiveIncident:
    item = _mapping(value)
    source = source_from_document(item["source"])
    evidence_sources = tuple(
        source_from_document(entry) for entry in _list(item, "evidence_sources")
    )
    sources_by_id = {entry.source_id: entry for entry in (source, *evidence_sources)}
    country_value = item.get("country")
    country = None
    if country_value is not None:
        country_item = _mapping(country_value)
        country = IncidentCountryAssociation(
            country_code=str(country_item["country_code"]),
            country_name=str(country_item["country_name"]),
            basis=CountryAssociationBasis(str(country_item["basis"])),
            distance_km=(
                float(country_item["distance_km"])
                if country_item.get("distance_km") is not None
                else None
            ),
        )
    detection_item = _mapping(item.get("detection", {}))
    return ActiveIncident(
        event_id=str(item["event_id"]),
        physical_event_id=(
            str(item["physical_event_id"])
            if item.get("physical_event_id") is not None
            else None
        ),
        disaster=Disaster(str(item["disaster"])),
        country=country,
        location=str(item["location"]),
        event_time=datetime.fromisoformat(str(item["event_time"])),
        geometry=geometry_from_document(item.get("geometry"), sources_by_id),
        measurements=tuple(
            measurement_from_document(entry, sources_by_id)
            for entry in _list(item, "measurements")
        ),
        provider_ids=tuple(str(entry) for entry in _list(item, "provider_ids")),
        lineage_ids=tuple(str(entry) for entry in _list(item, "lineage_ids")),
        provider_tier=ProviderTier(str(item["provider_tier"])),
        source_authority=SourceAuthority(str(item["source_authority"])),
        source=source,
        evidence_sources=evidence_sources,
        observation_kind=ObservationKind(str(item["observation_kind"])),
        activity_status=IncidentActivityStatus(str(item["activity_status"])),
        verification_status=IncidentCandidateStatus(
            str(item.get("verification_status", IncidentCandidateStatus.SOURCE_BACKED))
        ),
        detection=IncidentDetectionTimeline(
            news_break_at=_optional_datetime(detection_item.get("news_break_at")),
            first_observed_at=_optional_datetime(
                detection_item.get("first_observed_at")
            ),
            candidate_created_at=_optional_datetime(
                detection_item.get("candidate_created_at")
            ),
            verified_at=_optional_datetime(detection_item.get("verified_at")),
            monitor_visible_at=_optional_datetime(
                detection_item.get("monitor_visible_at")
            ),
            assistant_ready_at=_optional_datetime(
                detection_item.get("assistant_ready_at")
            ),
        ),
    )


def _optional_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _coverage_document(value: DisasterIncidentCoverage) -> dict[str, object]:
    return {
        "disaster": value.disaster.value,
        "state": value.state.value,
        "incident_count": value.incident_count,
        "providers": list(value.providers),
        "detail": value.detail,
        "scan_complete": value.scan_complete,
        "records_seen": value.records_seen,
        "truncated": value.truncated,
    }


def _coverage_from_document(value: object) -> DisasterIncidentCoverage:
    item = _mapping(value)
    return DisasterIncidentCoverage(
        disaster=Disaster(str(item["disaster"])),
        state=IncidentCoverageState(str(item["state"])),
        incident_count=int(item["incident_count"]),
        providers=tuple(str(entry) for entry in _list(item, "providers")),
        detail=str(item["detail"]),
        scan_complete=bool(item.get("scan_complete", True)),
        records_seen=int(item.get("records_seen", 0)),
        truncated=bool(item.get("truncated", False)),
    )


def _correlation_document(value: CompoundHazardCorrelation) -> dict[str, object]:
    return {
        "correlation_id": value.correlation_id,
        "rule_id": value.rule_id,
        "relationship": value.relationship.value,
        "first_event_id": value.first_event_id,
        "first_physical_event_id": value.first_physical_event_id,
        "first_disaster": value.first_disaster.value,
        "second_event_id": value.second_event_id,
        "second_physical_event_id": value.second_physical_event_id,
        "second_disaster": value.second_disaster.value,
        "distance_km": value.distance_km,
        "time_delta_seconds": value.time_delta_seconds,
        "source_ids": list(value.source_ids),
        "summary": value.summary,
        "limitation": value.limitation,
    }


def _correlation_from_document(value: object) -> CompoundHazardCorrelation:
    item = _mapping(value)
    return CompoundHazardCorrelation(
        correlation_id=str(item["correlation_id"]),
        rule_id=str(item["rule_id"]),
        relationship=CompoundHazardRelationship(str(item["relationship"])),
        first_event_id=str(item["first_event_id"]),
        first_physical_event_id=(
            str(item["first_physical_event_id"])
            if item.get("first_physical_event_id") is not None
            else None
        ),
        first_disaster=Disaster(str(item["first_disaster"])),
        second_event_id=str(item["second_event_id"]),
        second_physical_event_id=(
            str(item["second_physical_event_id"])
            if item.get("second_physical_event_id") is not None
            else None
        ),
        second_disaster=Disaster(str(item["second_disaster"])),
        distance_km=float(item["distance_km"]),
        time_delta_seconds=int(item["time_delta_seconds"]),
        source_ids=tuple(str(entry) for entry in _list(item, "source_ids")),
        summary=str(item["summary"]),
        limitation=str(item["limitation"]),
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Projection document values must be objects.")
    return cast(dict[str, Any], value)


def _list(value: dict[str, Any], key: str) -> list[object]:
    items = value.get(key, [])
    if not isinstance(items, list):
        raise ValueError(f"Projection field {key!r} must be a list.")
    return items
