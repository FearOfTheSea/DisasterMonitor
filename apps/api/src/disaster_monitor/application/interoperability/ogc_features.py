"""Narrow OGC API Features-style read-only incident projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from disaster_monitor.application.incidents.models import ActiveIncidentsSnapshot
from disaster_monitor.application.interoperability.exports import (
    export_incidents_geojson,
)


class OgcFeatureProjection:
    collections = ("incidents", "observations")

    def __init__(self, snapshot: ActiveIncidentsSnapshot) -> None:
        self._snapshot = snapshot

    def query(
        self,
        collection: str,
        *,
        bbox: tuple[float, float, float, float] | None = None,
        occurrence_start: datetime | None = None,
        occurrence_end: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        if collection not in self.collections:
            raise ValueError("The OGC feature collection is not supported.")
        if not 1 <= limit <= 1000:
            raise ValueError("The OGC feature limit must be between 1 and 1000.")
        if occurrence_start and occurrence_end and occurrence_end < occurrence_start:
            raise ValueError("The OGC occurrence interval is reversed.")
        source = export_incidents_geojson(self._snapshot)
        record_type = "incident" if collection == "incidents" else "observation"
        matches = [
            feature
            for feature in source["features"]
            if feature["properties"]["recordType"] == record_type
            and _matches_time(feature, occurrence_start, occurrence_end)
            and _matches_bbox(feature.get("geometry"), bbox)
        ]
        return {
            "type": "FeatureCollection",
            "timeStamp": _utc(self._snapshot.retrieved_at),
            "numberMatched": len(matches),
            "numberReturned": min(limit, len(matches)),
            "features": matches[:limit],
            "links": [
                {
                    "rel": "self",
                    "type": "application/geo+json",
                    "href": f"/api/v1/ogc/collections/{collection}/items",
                }
            ],
        }


def _matches_time(
    feature: dict[str, Any], start: datetime | None, end: datetime | None
) -> bool:
    value = datetime.fromisoformat(
        feature["properties"]["eventTime"].replace("Z", "+00:00")
    )
    return not (
        (start is not None and value < start) or (end is not None and value > end)
    )


def _matches_bbox(
    geometry: dict[str, Any] | None,
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    if bbox is None:
        return True
    if geometry is None:
        return False
    west, south, east, north = bbox
    points = _coordinate_pairs(geometry["coordinates"])
    return any(
        west <= longitude <= east and south <= latitude <= north
        for longitude, latitude in points
    )


def _coordinate_pairs(value: Any) -> list[tuple[float, float]]:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, (int, float)) for item in value)
    ):
        return [(float(value[0]), float(value[1]))]
    if isinstance(value, list):
        return [pair for child in value for pair in _coordinate_pairs(child)]
    return []


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["OgcFeatureProjection"]
