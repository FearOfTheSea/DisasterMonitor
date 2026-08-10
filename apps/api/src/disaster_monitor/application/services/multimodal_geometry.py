"""Central WGS84 geometry validation and spatial matching policy."""

from math import asin, cos, radians, sin, sqrt

from disaster_monitor.domain.multimodal import GeoPoint, GeoPolygon, MapGeometry

MAX_POLYGON_POINTS = 4_096


class MultimodalGeometryPolicy:
    """Validate bounded geometry before it reaches association or rendering."""

    def polygon(
        self,
        rings: tuple[tuple[tuple[float, float], ...], ...],
        *,
        crs: str,
    ) -> GeoPolygon:
        polygon = GeoPolygon(
            tuple(
                tuple(GeoPoint(longitude, latitude) for longitude, latitude in ring)
                for ring in rings
            ),
            crs=crs,
        )
        self.validate(polygon)
        return polygon

    def validate(self, geometry: MapGeometry) -> None:
        """Reject degenerate or self-intersecting polygon rings."""
        if not isinstance(geometry, GeoPolygon):
            return
        if sum(len(ring) for ring in geometry.rings) > MAX_POLYGON_POINTS:
            raise ValueError("Polygon geometry exceeds the bounded point count.")
        for ring in geometry.rings:
            if abs(_signed_area(ring)) < 1e-12:
                raise ValueError("Polygon rings must enclose a non-zero area.")
            if _self_intersects(ring):
                raise ValueError("Polygon rings must not self-intersect.")
        exterior = geometry.rings[0]
        holes = geometry.rings[1:]
        for hole in holes:
            if _rings_intersect(exterior, hole) or any(
                _point_on_ring(point, exterior) or not _point_in_ring(point, exterior)
                for point in hole[:-1]
            ):
                raise ValueError("Polygon holes must remain inside the exterior ring.")
        for first_index, first in enumerate(holes):
            for second in holes[first_index + 1 :]:
                if (
                    _rings_intersect(first, second)
                    or _point_in_ring(first[0], second)
                    or _point_in_ring(second[0], first)
                ):
                    raise ValueError("Polygon holes must not overlap.")

    def contains(self, polygon: GeoPolygon, point: GeoPoint) -> bool:
        """Return point-in-polygon membership including the exterior boundary."""
        if _point_on_ring(point, polygon.rings[0]):
            return True
        inside = _point_in_ring(point, polygon.rings[0])
        if not inside:
            return False
        return not any(
            _point_on_ring(point, hole) or _point_in_ring(point, hole)
            for hole in polygon.rings[1:]
        )

    def distance_to_polygon_km(self, polygon: GeoPolygon, point: GeoPoint) -> float:
        """Return zero inside, otherwise the nearest WGS84 ring-segment distance."""
        if self.contains(polygon, point):
            return 0.0
        return min(
            _point_segment_distance_km(point, first, second)
            for ring in polygon.rings
            for first, second in zip(ring, ring[1:], strict=False)
        )


def _signed_area(ring: tuple[GeoPoint, ...]) -> float:
    return (
        sum(
            first.longitude * second.latitude - second.longitude * first.latitude
            for first, second in zip(ring, ring[1:], strict=False)
        )
        / 2
    )


def _orientation(first: GeoPoint, second: GeoPoint, third: GeoPoint) -> float:
    return (second.longitude - first.longitude) * (third.latitude - first.latitude) - (
        second.latitude - first.latitude
    ) * (third.longitude - first.longitude)


def _on_segment(first: GeoPoint, second: GeoPoint, point: GeoPoint) -> bool:
    return (
        min(first.longitude, second.longitude)
        <= point.longitude
        <= max(first.longitude, second.longitude)
        and min(first.latitude, second.latitude)
        <= point.latitude
        <= max(first.latitude, second.latitude)
        and abs(_orientation(first, second, point)) < 1e-12
    )


def _segments_intersect(
    first: GeoPoint, second: GeoPoint, third: GeoPoint, fourth: GeoPoint
) -> bool:
    orientations = (
        _orientation(first, second, third),
        _orientation(first, second, fourth),
        _orientation(third, fourth, first),
        _orientation(third, fourth, second),
    )
    if orientations[0] * orientations[1] < 0 and orientations[2] * orientations[3] < 0:
        return True
    return any(
        abs(orientation) < 1e-12 and _on_segment(start, end, point)
        for orientation, start, end, point in (
            (orientations[0], first, second, third),
            (orientations[1], first, second, fourth),
            (orientations[2], third, fourth, first),
            (orientations[3], third, fourth, second),
        )
    )


def _self_intersects(ring: tuple[GeoPoint, ...]) -> bool:
    segments = tuple(zip(ring, ring[1:], strict=False))
    last = len(segments) - 1
    for first_index, (first_start, first_end) in enumerate(segments):
        for second_index in range(first_index + 1, len(segments)):
            if second_index in {first_index, first_index + 1} or (
                first_index == 0 and second_index == last
            ):
                continue
            second_start, second_end = segments[second_index]
            if _segments_intersect(first_start, first_end, second_start, second_end):
                return True
    return False


def _rings_intersect(first: tuple[GeoPoint, ...], second: tuple[GeoPoint, ...]) -> bool:
    return any(
        _segments_intersect(first_start, first_end, second_start, second_end)
        for first_start, first_end in zip(first, first[1:], strict=False)
        for second_start, second_end in zip(second, second[1:], strict=False)
    )


def _point_on_ring(point: GeoPoint, ring: tuple[GeoPoint, ...]) -> bool:
    return any(
        _on_segment(first, second, point)
        for first, second in zip(ring, ring[1:], strict=False)
    )


def _point_in_ring(point: GeoPoint, ring: tuple[GeoPoint, ...]) -> bool:
    inside = False
    for first, second in zip(ring, ring[1:], strict=False):
        if (first.latitude > point.latitude) == (second.latitude > point.latitude):
            continue
        boundary_longitude = first.longitude + (
            (point.latitude - first.latitude)
            * (second.longitude - first.longitude)
            / (second.latitude - first.latitude)
        )
        if point.longitude < boundary_longitude:
            inside = not inside
    return inside


def _distance_km(first: GeoPoint, second: GeoPoint) -> float:
    first_latitude = radians(first.latitude)
    second_latitude = radians(second.latitude)
    latitude_delta = second_latitude - first_latitude
    longitude_delta = radians(second.longitude - first.longitude)
    value = (
        sin(latitude_delta / 2) ** 2
        + cos(first_latitude) * cos(second_latitude) * sin(longitude_delta / 2) ** 2
    )
    return 6371.0088 * 2 * asin(min(1.0, sqrt(value)))


def _point_segment_distance_km(
    point: GeoPoint, first: GeoPoint, second: GeoPoint
) -> float:
    """Use a bounded local equirectangular projection for segment distance."""
    latitude_scale = 111.32
    longitude_scale = 111.32 * cos(radians(point.latitude))
    ax = (first.longitude - point.longitude) * longitude_scale
    ay = (first.latitude - point.latitude) * latitude_scale
    bx = (second.longitude - point.longitude) * longitude_scale
    by = (second.latitude - point.latitude) * latitude_scale
    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return _distance_km(point, first)
    ratio = max(0.0, min(1.0, -(ax * dx + ay * dy) / length_squared))
    return sqrt((ax + ratio * dx) ** 2 + (ay + ratio * dy) ** 2)
