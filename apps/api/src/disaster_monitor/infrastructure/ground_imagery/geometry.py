"""Metric geometry adapter for imagery region planning and coverage."""

from __future__ import annotations

from collections.abc import Callable
from math import atan2, ceil, cos, degrees, radians, sin
from typing import Any

from pyproj import CRS, Geod, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from disaster_monitor.application.ports.ground_imagery.geometry import (
    GeometryComputationError,
)
from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid
from disaster_monitor.domain.imagery.observations import Sensor
from disaster_monitor.domain.imagery.regions import (
    Coordinate,
    LinearRing,
    MultiPolygon,
    Polygon,
)

_WGS84 = Geod(ellps="WGS84")


class GeodesicGeometryEngine:
    """Use a local metric projection for buffers and geodesic area for limits."""

    def validate(self, geometry: MultiPolygon) -> None:
        if geometry.positions > 100_000:
            raise GeometryComputationError(
                "The imagery region exceeds the 100,000-position limit."
            )
        candidate = _to_shapely(geometry)
        if candidate.is_empty or not candidate.is_valid:
            raise GeometryComputationError(
                "The imagery region has invalid polygon topology; draw or select a "
                "valid boundary without automatic repair."
            )

    def buffer(self, geometry: MultiPolygon, distance_km: float) -> MultiPolygon:
        if distance_km < 0 or distance_km > 20:
            raise GeometryComputationError(
                "The metric buffer must be between 0 and 20 km."
            )
        self.validate(geometry)
        if distance_km == 0:
            return geometry
        origin_latitude, origin_longitude = _geometry_center(geometry)
        forward, inverse = _metric_transformers(origin_latitude, origin_longitude)
        buffered = transform(
            inverse,
            transform(forward, _to_shapely(geometry)).buffer(distance_km * 1000),
        )
        return _from_shapely(buffered)

    def buffer_point(self, point: Coordinate, radius_km: float) -> MultiPolygon:
        if not 0 < radius_km <= 200:
            raise GeometryComputationError(
                "The point buffer must be between 0 and 200 km."
            )
        azimuths = range(0, 360, 5)
        coordinates = tuple(
            Coordinate(latitude, longitude)
            for azimuth in azimuths
            for longitude, latitude, _ in (
                _WGS84.fwd(point.longitude, point.latitude, azimuth, radius_km * 1000),
            )
        )
        closed = coordinates + (coordinates[0],)
        return MultiPolygon((Polygon(LinearRing(closed)),))

    def union(self, geometries: tuple[MultiPolygon, ...]) -> MultiPolygon:
        if not geometries:
            raise GeometryComputationError(
                "At least one geometry is required for union."
            )
        for geometry in geometries:
            self.validate(geometry)
        return _from_shapely(unary_union([_to_shapely(item) for item in geometries]))

    def area_km2(self, geometry: MultiPolygon) -> float:
        self.validate(geometry)
        area, _ = _WGS84.geometry_area_perimeter(_to_shapely(geometry))
        return abs(area) / 1_000_000

    def intersection_area_km2(self, first: MultiPolygon, second: MultiPolygon) -> float:
        self.validate(first)
        self.validate(second)
        origin_latitude, origin_longitude = _geometry_center(first)
        forward, inverse = _metric_transformers(origin_latitude, origin_longitude)
        intersection = transform(
            inverse,
            transform(forward, _to_shapely(first)).intersection(
                transform(forward, _to_shapely(second))
            ),
        )
        area, _ = _WGS84.geometry_area_perimeter(intersection)
        return abs(area) / 1_000_000

    def plan_grid(
        self, geometry: MultiPolygon, sensor: Sensor, *, overview: bool = True
    ) -> ImageryGrid:
        """Plan a bounded local-metric grid without increasing native detail."""
        self.validate(geometry)
        latitude, longitude = _geometry_center(geometry)
        grid_crs = _grid_crs(latitude, longitude)
        forward = Transformer.from_crs("EPSG:4326", grid_crs, always_xy=True).transform
        projected = transform(forward, _to_shapely(geometry))
        min_x, min_y, max_x, max_y = projected.bounds
        native_pixel_size = 10.0 if sensor is Sensor.SENTINEL_2 else 20.0
        pixel_size = 40.0 if overview else native_pixel_size
        required_size = max(
            (max_x - min_x) / 2_048,
            (max_y - min_y) / 2_048,
            native_pixel_size,
        )
        if required_size > pixel_size:
            pixel_size = ceil(required_size / 10.0) * 10.0
        width = max(1, ceil((max_x - min_x) / pixel_size))
        height = max(1, ceil((max_y - min_y) / pixel_size))
        return ImageryGrid(
            crs=grid_crs.to_string(),
            min_x=min_x,
            min_y=min_y,
            max_x=max_x,
            max_y=max_y,
            pixel_size_m=pixel_size,
            width=min(width, 2_048),
            height=min(height, 2_048),
            resolution_label=(
                f"overview-{pixel_size:g}m" if overview else f"native-{pixel_size:g}m"
            ),
        )


def _to_shapely(geometry: MultiPolygon) -> Any:
    return shape(geometry.as_geojson())


def _from_shapely(geometry: Any) -> MultiPolygon:
    document = mapping(geometry)
    if document["type"] == "Polygon":
        polygons = [document["coordinates"]]
    elif document["type"] == "MultiPolygon":
        polygons = document["coordinates"]
    else:
        raise GeometryComputationError("Metric geometry produced a non-area result.")
    converted: list[Polygon] = []
    for raw_polygon in polygons:
        rings = [
            LinearRing(
                tuple(
                    Coordinate(float(latitude), float(longitude))
                    for longitude, latitude in ring
                )
            )
            for ring in raw_polygon
        ]
        converted.append(Polygon(rings[0], tuple(rings[1:])))
    result = MultiPolygon(tuple(converted))
    if result.positions > 100_000:
        raise GeometryComputationError("Metric geometry exceeded the position limit.")
    return result


def _geometry_center(geometry: MultiPolygon) -> tuple[float, float]:
    points = [
        point
        for polygon in geometry.polygons
        for point in polygon.exterior.coordinates[:-1]
    ]
    latitude = sum(point.latitude for point in points) / len(points)
    longitude = degrees(
        atan2(
            sum(
                cos(radians(point.latitude)) * sin(radians(point.longitude))
                for point in points
            ),
            sum(
                cos(radians(point.latitude)) * cos(radians(point.longitude))
                for point in points
            ),
        )
    )
    return latitude, longitude


def _metric_transformers(
    latitude: float, longitude: float
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    local = _metric_crs(latitude, longitude)
    forward = Transformer.from_crs("EPSG:4326", local, always_xy=True).transform
    inverse = Transformer.from_crs(local, "EPSG:4326", always_xy=True).transform
    return forward, inverse


def _metric_crs(latitude: float, longitude: float) -> CRS:
    return CRS.from_proj4(
        f"+proj=laea +lat_0={latitude:.10f} +lon_0={longitude:.10f} "
        "+datum=WGS84 +units=m +no_defs"
    )


def _grid_crs(latitude: float, longitude: float) -> CRS:
    if latitude >= 84:
        return CRS.from_epsg(32661)
    if latitude <= -80:
        return CRS.from_epsg(32761)
    zone = min(60, max(1, int((longitude + 180) // 6) + 1))
    return CRS.from_epsg((32600 if latitude >= 0 else 32700) + zone)
