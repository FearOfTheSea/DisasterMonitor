"""Canonical incident-watch fingerprints and persistence documents."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from disaster_monitor.domain.disaster_types import Disaster, ProviderTier
from disaster_monitor.domain.events import (
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
    EventMeasurement,
    MeasurementKind,
)
from disaster_monitor.domain.evidence_types import SourceAuthority, SourceReference

if TYPE_CHECKING:
    from disaster_monitor.domain.incident_watch import WatchIncident


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def watch_incident_document(value: WatchIncident) -> dict[str, object]:
    return {
        "physical_event_id": value.physical_event_id,
        "event_id": value.event_id,
        "disaster": value.disaster.value,
        "location": value.location,
        "event_time": value.event_time.isoformat(),
        "geometry": geometry_document(value.geometry),
        "measurements": [measurement_document(item) for item in value.measurements],
        "provider_ids": list(value.provider_ids),
        "provider_tier": value.provider_tier.value,
        "source_authority": value.source_authority.value,
        "source": source_document(value.source),
        "evidence_sources": [source_document(item) for item in value.evidence_sources],
    }


def watch_incident_from_document(value: object) -> WatchIncident:
    from disaster_monitor.domain.incident_watch import WatchIncident

    item = _mapping(value)
    source_value = source_from_document(item["source"])
    evidence_sources = tuple(
        source_from_document(entry)
        for entry in cast(list[object], item.get("evidence_sources", []))
    )
    sources_by_id = {
        source.source_id: source for source in (source_value, *evidence_sources)
    }
    return WatchIncident.from_source_evidence(
        physical_event_id=str(item["physical_event_id"]),
        event_id=str(item["event_id"]),
        disaster=Disaster(str(item["disaster"])),
        location=str(item["location"]),
        event_time=datetime.fromisoformat(str(item["event_time"])),
        geometry=geometry_from_document(item.get("geometry"), sources_by_id),
        measurements=tuple(
            measurement_from_document(entry, sources_by_id)
            for entry in cast(list[object], item.get("measurements", []))
        ),
        provider_ids=tuple(str(entry) for entry in item.get("provider_ids", [])),
        provider_tier=ProviderTier(str(item["provider_tier"])),
        source_authority=SourceAuthority(str(item["source_authority"])),
        source=source_value,
        evidence_sources=evidence_sources,
    )


def source_document(value: SourceReference) -> dict[str, object]:
    return {
        "source_id": value.source_id,
        "publisher": value.publisher,
        "title": value.title,
        "canonical_url": value.canonical_url,
        "published_at": _optional_datetime(value.published_at),
        "updated_at": _optional_datetime(value.updated_at),
        "retrieved_at": value.retrieved_at.isoformat(),
        "authority": value.authority.value,
        "snapshot_id": value.snapshot_id,
    }


def source_evidence_document(value: SourceReference) -> dict[str, object]:
    document = source_document(value)
    document.pop("retrieved_at")
    return document


def source_from_document(value: object) -> SourceReference:
    item = _mapping(value)
    return SourceReference(
        source_id=str(item["source_id"]),
        publisher=str(item["publisher"]),
        title=str(item["title"]),
        canonical_url=str(item["canonical_url"]),
        published_at=_parse_optional_datetime(item.get("published_at")),
        updated_at=_parse_optional_datetime(item.get("updated_at")),
        retrieved_at=datetime.fromisoformat(str(item["retrieved_at"])),
        authority=SourceAuthority(str(item["authority"])),
        snapshot_id=(str(item["snapshot_id"]) if item.get("snapshot_id") else None),
    )


def geometry_document(value: EventGeometry | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "kind": value.kind.value,
        "coordinates": [
            {"latitude": item.latitude, "longitude": item.longitude}
            for item in value.coordinates
        ],
        "description": value.description,
        "source_id": value.source.source_id,
        "estimated": value.estimated,
    }


def geometry_from_document(
    value: object, sources_by_id: dict[str, SourceReference]
) -> EventGeometry | None:
    if value is None:
        return None
    item = _mapping(value)
    source = _document_source(item, sources_by_id)
    return EventGeometry(
        kind=EventGeometryKind(str(item["kind"])),
        source=source,
        coordinates=tuple(
            EventCoordinate(
                float(_mapping(entry)["latitude"]),
                float(_mapping(entry)["longitude"]),
            )
            for entry in cast(list[object], item.get("coordinates", []))
        ),
        description=(str(item["description"]) if item.get("description") else None),
        estimated=bool(item.get("estimated", False)),
    )


def measurement_document(value: EventMeasurement) -> dict[str, object]:
    return {
        "kind": value.kind.value,
        "value": value.value,
        "unit": value.unit,
        "source_id": value.source.source_id,
    }


def measurement_from_document(
    value: object, sources_by_id: dict[str, SourceReference]
) -> EventMeasurement:
    item = _mapping(value)
    source = _document_source(item, sources_by_id)
    return EventMeasurement(
        MeasurementKind(str(item["kind"])),
        cast(float | str, item["value"]),
        str(item["unit"]) if item.get("unit") is not None else None,
        source=source,
    )


def _document_source(
    item: dict[str, Any], sources_by_id: dict[str, SourceReference]
) -> SourceReference:
    source_id = str(item["source_id"])
    try:
        return sources_by_id[source_id]
    except KeyError as error:
        raise ValueError(
            f"Watch incident references unknown evidence source {source_id!r}."
        ) from error


def _stable_physical_event_id(disaster: Disaster, source_id: str, event_id: str) -> str:
    material = f"{disaster.value}|{source_id.casefold()}|{event_id.casefold()}"
    return "watch-event:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _source_order_key(value: SourceReference) -> tuple[str, str, str, str]:
    return (
        value.source_id,
        value.canonical_url,
        _optional_datetime(value.updated_at) or "",
        value.snapshot_id or "",
    )


def _measurement_order_key(
    value: EventMeasurement,
) -> tuple[str, str, str, str]:
    return (
        value.kind.value,
        str(value.value),
        value.unit or "",
        value.source.source_id,
    )


def _optional_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Watch incident document must be an object.")
    return cast(dict[str, Any], value)


def _require_aware(value: datetime, message: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(message)


def _valid_prefixed_sha256(value: str) -> bool:
    prefix, separator, digest = value.partition(":")
    if prefix != "sha256" or separator != ":" or len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True
