"""Reproducible critical-infrastructure queries over a local OSM GeoJSON extract."""

import json
from pathlib import Path

from disaster_monitor.domain.exposure import (
    ExposureGeometry,
    InfrastructureAsset,
    InfrastructureCategory,
)
from disaster_monitor.domain.imagery.regions import (
    Coordinate,
    contains_coordinate,
    geometries_intersect,
    path_intersects_geometry,
    polygon_from_geojson,
)

_AMENITIES = {
    "hospital": InfrastructureCategory.HOSPITAL,
    "clinic": InfrastructureCategory.CLINIC,
    "school": InfrastructureCategory.SCHOOL,
    "fire_station": InfrastructureCategory.FIRE_STATION,
    "police": InfrastructureCategory.POLICE,
    "shelter": InfrastructureCategory.SHELTER,
}
_MAJOR_ROADS = {"motorway", "trunk", "primary", "secondary"}


class LocalOsmAssetExposure:
    def __init__(self, extract_path: Path, *, extract_version: str) -> None:
        if not extract_path.is_file() or not extract_version.strip():
            raise ValueError("A local OSM extract and version are required.")
        self._path = extract_path
        self._version = extract_version

    async def intersecting_assets(
        self, geometry: ExposureGeometry
    ) -> tuple[InfrastructureAsset, ...]:
        document = json.loads(self._path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("type") != "FeatureCollection"
        ):
            raise ValueError(
                "The local OSM extract must be a GeoJSON FeatureCollection."
            )
        features = document.get("features")
        if not isinstance(features, list) or len(features) > 1_000_000:
            raise ValueError(
                "The local OSM extract feature list is invalid or unbounded."
            )
        results = []
        for raw in features:
            asset = _asset(raw, self._version)
            if asset is not None and _intersects(asset, geometry):
                results.append(asset)
        return tuple(sorted(results, key=lambda item: item.asset_id))


def _asset(raw: object, version: str) -> InfrastructureAsset | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("properties"), dict):
        return None
    properties = raw["properties"]
    category = _category(properties)
    raw_geometry = raw.get("geometry")
    if category is None or not isinstance(raw_geometry, dict):
        return None
    asset_id = str(raw.get("id") or properties.get("osm_id") or "").strip()
    name = str(properties.get("name") or category.value.replace("_", " ")).strip()
    geometry_type = raw_geometry.get("type")
    coordinates = raw_geometry.get("coordinates")
    try:
        if (
            geometry_type == "Point"
            and isinstance(coordinates, list)
            and len(coordinates) >= 2
        ):
            return InfrastructureAsset(
                asset_id=asset_id,
                name=name,
                category=category,
                source_dataset_id="openstreetmap-local",
                source_version=version,
                coordinate=Coordinate(float(coordinates[1]), float(coordinates[0])),
            )
        if geometry_type in {"Polygon", "MultiPolygon"}:
            return InfrastructureAsset(
                asset_id=asset_id,
                name=name,
                category=category,
                source_dataset_id="openstreetmap-local",
                source_version=version,
                geometry=polygon_from_geojson(raw_geometry),
            )
        if geometry_type == "LineString" and isinstance(coordinates, list):
            return InfrastructureAsset(
                asset_id=asset_id,
                name=name,
                category=category,
                source_dataset_id="openstreetmap-local",
                source_version=version,
                path=tuple(
                    Coordinate(float(item[1]), float(item[0])) for item in coordinates
                ),
            )
    except (TypeError, ValueError, IndexError):
        return None
    return None


def _category(properties: dict[str, object]) -> InfrastructureCategory | None:
    amenity = str(properties.get("amenity") or "")
    if amenity in _AMENITIES:
        return _AMENITIES[amenity]
    if str(properties.get("emergency") or "") == "shelter":
        return InfrastructureCategory.SHELTER
    if str(properties.get("bridge") or "") not in {"", "no"}:
        return InfrastructureCategory.BRIDGE
    if str(properties.get("highway") or "") in _MAJOR_ROADS:
        return InfrastructureCategory.MAJOR_ROAD
    if str(properties.get("power") or "") in {"plant", "substation", "line"}:
        return InfrastructureCategory.POWER
    if str(properties.get("man_made") or "") in {
        "water_works",
        "water_tower",
        "pipeline",
    }:
        return InfrastructureCategory.WATER
    return None


def _intersects(asset: InfrastructureAsset, geometry: ExposureGeometry) -> bool:
    if asset.coordinate is not None:
        return contains_coordinate(geometry.geometry, asset.coordinate)
    if asset.geometry is not None:
        return geometries_intersect(geometry.geometry, asset.geometry)
    return path_intersects_geometry(asset.path, geometry.geometry)
