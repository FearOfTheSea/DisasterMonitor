"""Deterministic GeoJSON, CSV, STAC, and HXL exporters."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from disaster_monitor.application.incidents.models import (
    ActiveIncident,
    ActiveIncidentsSnapshot,
)
from disaster_monitor.domain.disaster import EventGeometryKind, IncidentWatchChange


@dataclass(frozen=True, slots=True)
class StacArtifactRecord:
    artifact_id: str
    incident_id: str
    datetime: datetime
    geometry: dict[str, Any]
    bbox: tuple[float, float, float, float]
    asset_href: str
    media_type: str
    roles: tuple[str, ...]
    source_product_ids: tuple[str, ...]
    algorithm_version: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.artifact_id, self.incident_id, self.asset_href)
        ):
            raise ValueError("STAC artifacts require stable identity and a link.")
        if self.datetime.tzinfo is None or self.datetime.utcoffset() is None:
            raise ValueError("STAC artifact times must be timezone-aware.")
        if not self.source_product_ids:
            raise ValueError("STAC artifacts require source product identity.")


@dataclass(frozen=True, slots=True)
class HumanitarianContextRow:
    country_code: str
    admin_name: str
    indicator: str
    value: str
    unit: str
    source_url: str
    as_of: datetime

    def __post_init__(self) -> None:
        if len(self.country_code) != 3 or not self.country_code.isalpha():
            raise ValueError("HXL context requires an ISO alpha-3 country code.")
        if not all(
            value.strip()
            for value in (
                self.admin_name,
                self.indicator,
                self.value,
                self.unit,
                self.source_url,
            )
        ):
            raise ValueError("HXL context fields must not be empty.")
        if not self.source_url.startswith("https://"):
            raise ValueError("HXL sources require HTTPS URLs.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("HXL context times must be timezone-aware.")


def export_incidents_geojson(snapshot: ActiveIncidentsSnapshot) -> dict[str, Any]:
    features = [
        _incident_feature(incident, record_type="incident")
        for incident in snapshot.incidents
    ]
    features.extend(
        _incident_feature(observation, record_type="observation")
        for observation in snapshot.observations
    )
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "snapshotVersion": snapshot.snapshot_version,
            "retrievedAt": _utc(snapshot.retrieved_at),
            "coverage": {
                item.disaster.value: item.state.value for item in snapshot.coverage
            },
        },
    }


def export_incidents_csv(snapshot: ActiveIncidentsSnapshot) -> str:
    output = io.StringIO(newline="")
    fields = (
        "record_type",
        "event_id",
        "physical_event_id",
        "disaster",
        "event_time",
        "location",
        "country_code",
        "geometry_type",
        "geometry_meaning",
        "source_id",
        "source_authority",
        "source_url",
        "retrieved_at",
        "coverage_state",
    )
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    coverage = {item.disaster: item.state.value for item in snapshot.coverage}
    for record_type, records in (
        ("incident", snapshot.incidents),
        ("observation", snapshot.observations),
    ):
        for incident in records:
            writer.writerow(
                {
                    "record_type": record_type,
                    "event_id": incident.event_id,
                    "physical_event_id": incident.physical_event_id or "",
                    "disaster": incident.disaster.value,
                    "event_time": _utc(incident.event_time),
                    "location": incident.location,
                    "country_code": (
                        incident.country.country_code if incident.country else ""
                    ),
                    "geometry_type": (
                        incident.geometry.kind.value if incident.geometry else ""
                    ),
                    "geometry_meaning": _geometry_meaning(incident),
                    "source_id": incident.source.source_id,
                    "source_authority": incident.source_authority.value,
                    "source_url": incident.source.canonical_url,
                    "retrieved_at": _utc(incident.source.retrieved_at),
                    "coverage_state": coverage.get(incident.disaster, "unavailable"),
                }
            )
    return output.getvalue()


def export_findings_geojson(
    changes: tuple[IncidentWatchChange, ...],
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": change.change_id,
                "geometry": (
                    _geometry_geojson(change.incident.geometry)
                    if change.incident is not None
                    else None
                ),
                "properties": {
                    "recordType": "finding",
                    "watchId": change.watch_id,
                    "kind": change.kind.value,
                    "summary": change.summary,
                    "detail": change.detail,
                    "createdAt": _utc(change.created_at),
                    "sourceIds": list(change.source_ids),
                },
            }
            for change in changes
        ],
    }


def export_findings_csv(changes: tuple[IncidentWatchChange, ...]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "change_id",
            "watch_id",
            "kind",
            "summary",
            "detail",
            "created_at",
            "event_id",
            "source_ids",
        )
    )
    for change in changes:
        writer.writerow(
            (
                change.change_id,
                change.watch_id,
                change.kind.value,
                change.summary,
                change.detail,
                _utc(change.created_at),
                change.incident.event_id if change.incident is not None else "",
                "|".join(change.source_ids),
            )
        )
    return output.getvalue()


def export_stac_catalog(records: tuple[StacArtifactRecord, ...]) -> dict[str, Any]:
    items = [_stac_item(record) for record in records]
    links: list[dict[str, str]] = [{"rel": "self", "href": "./catalog.json"}]
    links.extend(
        {"rel": "item", "href": f"./items/{record.artifact_id}.json"}
        for record in records
    )
    return {
        "stac_version": "1.0.0",
        "type": "Catalog",
        "id": "disaster-monitor-ground-artifacts",
        "description": "Credential-free DisasterMonitor Ground artifact catalog.",
        "links": links,
        "items": items,
    }


def export_hxl_csv(rows: tuple[HumanitarianContextRow, ...]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "Country code",
            "Admin area",
            "Indicator",
            "Value",
            "Unit",
            "Source",
            "As of",
        )
    )
    writer.writerow(
        (
            "#country+code",
            "#adm1+name",
            "#indicator+name",
            "#indicator+value",
            "#indicator+unit",
            "#meta+url",
            "#date+reported",
        )
    )
    for row in rows:
        writer.writerow(
            (
                row.country_code.upper(),
                row.admin_name,
                row.indicator,
                row.value,
                row.unit,
                row.source_url,
                _utc(row.as_of),
            )
        )
    return output.getvalue()


def _incident_feature(incident: ActiveIncident, *, record_type: str) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": incident.event_id,
        "geometry": _event_geojson(incident),
        "properties": {
            "recordType": record_type,
            "physicalEventId": incident.physical_event_id,
            "disaster": incident.disaster.value,
            "eventTime": _utc(incident.event_time),
            "location": incident.location,
            "countryCode": (
                incident.country.country_code if incident.country else None
            ),
            "geometryMeaning": _geometry_meaning(incident),
            "sourceId": incident.source.source_id,
            "sourceAuthority": incident.source_authority.value,
            "sourceUrl": incident.source.canonical_url,
            "providerIds": list(incident.provider_ids),
            "lineageIds": list(incident.lineage_ids),
        },
    }


def _event_geojson(incident: ActiveIncident) -> dict[str, Any] | None:
    return _geometry_geojson(incident.geometry)


def _geometry_geojson(geometry: Any) -> dict[str, Any] | None:
    if geometry is None or geometry.kind is EventGeometryKind.DESCRIPTIVE:
        return None
    coordinates = [
        [coordinate.longitude, coordinate.latitude]
        for coordinate in geometry.coordinates
    ]
    if geometry.kind is EventGeometryKind.POINT:
        return {"type": "Point", "coordinates": coordinates[0]}
    if geometry.kind is EventGeometryKind.TRACK:
        return {"type": "LineString", "coordinates": coordinates}
    if coordinates and coordinates[0] != coordinates[-1]:
        coordinates.append(coordinates[0])
    return {"type": "Polygon", "coordinates": [coordinates]}


def _geometry_meaning(incident: ActiveIncident) -> str:
    geometry = incident.geometry
    if geometry is None:
        return "no_source_geometry"
    qualifier = "estimated" if geometry.estimated else "source_backed"
    return f"{qualifier}_event_{geometry.kind.value}"


def _stac_item(record: StacArtifactRecord) -> dict[str, Any]:
    return {
        "stac_version": "1.0.0",
        "type": "Feature",
        "id": record.artifact_id,
        "geometry": record.geometry,
        "bbox": list(record.bbox),
        "properties": {
            "datetime": _utc(record.datetime),
            "disaster-monitor:incident_id": record.incident_id,
            "disaster-monitor:source_product_ids": list(record.source_product_ids),
            "disaster-monitor:algorithm_version": record.algorithm_version,
        },
        "links": [],
        "assets": {
            "data": {
                "href": record.asset_href,
                "type": record.media_type,
                "roles": list(record.roles),
            }
        },
    }


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "HumanitarianContextRow",
    "StacArtifactRecord",
    "export_findings_csv",
    "export_findings_geojson",
    "export_hxl_csv",
    "export_incidents_csv",
    "export_incidents_geojson",
    "export_stac_catalog",
]
