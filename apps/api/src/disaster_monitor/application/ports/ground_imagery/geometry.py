"""Application-owned geometry computation seam."""

from typing import Protocol

from disaster_monitor.application.ports.ground_imagery.rendering import ImageryGrid
from disaster_monitor.domain.imagery.observations import Sensor
from disaster_monitor.domain.imagery.regions import Coordinate, MultiPolygon


class GeometryComputationError(ValueError):
    """A source geometry cannot be safely used for imagery planning."""


class RegionGeometryEngine(Protocol):
    """Metric geometry operations implemented behind infrastructure."""

    def validate(self, geometry: MultiPolygon) -> None: ...

    def buffer(self, geometry: MultiPolygon, distance_km: float) -> MultiPolygon: ...

    def buffer_point(self, point: Coordinate, radius_km: float) -> MultiPolygon: ...

    def union(self, geometries: tuple[MultiPolygon, ...]) -> MultiPolygon: ...

    def area_km2(self, geometry: MultiPolygon) -> float: ...

    def intersection_area_km2(
        self, first: MultiPolygon, second: MultiPolygon
    ) -> float: ...

    def plan_grid(
        self, geometry: MultiPolygon, sensor: Sensor, *, overview: bool = True
    ) -> ImageryGrid: ...
