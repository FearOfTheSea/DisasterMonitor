"""Geometry validation helpers for NASA EONET country-scoped queries."""

from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.disaster import Country, EventGeometry, EventGeometryKind


def observation_matches_country(
    geometry: EventGeometry,
    country: Country | None,
    geography: CountryCatalog | None,
) -> bool:
    if country is None:
        return True
    if geography is None:
        return False
    projected_country = geography.get_by_alpha3(country.alpha3_code)
    if projected_country is None:
        return False
    if geometry.kind is EventGeometryKind.POINT:
        point = geometry.coordinates[0]
        return geography.contains(projected_country, point.latitude, point.longitude)
    event_ring = tuple(
        (point.latitude, point.longitude) for point in geometry.coordinates
    )
    country_polygons = projected_country.geographic_area.polygons
    if not country_polygons:
        return any(
            geography.contains(projected_country, latitude, longitude)
            for latitude, longitude in event_ring
        )
    return any(_polygons_intersect(event_ring, polygon) for polygon in country_polygons)


def _point_in_ring(
    latitude: float, longitude: float, ring: tuple[tuple[float, float], ...]
) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        current_latitude, current_longitude = current
        previous_latitude, previous_longitude = previous
        intersects = (current_latitude > latitude) != (previous_latitude > latitude)
        if intersects:
            boundary_longitude = (previous_longitude - current_longitude) * (
                latitude - current_latitude
            ) / (previous_latitude - current_latitude) + current_longitude
            if longitude <= boundary_longitude:
                inside = not inside
        previous = current
    return inside


def _orientation(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    return (second[1] - first[1]) * (third[0] - first[0]) - (second[0] - first[0]) * (
        third[1] - first[1]
    )


def _on_segment(
    first: tuple[float, float],
    second: tuple[float, float],
    point: tuple[float, float],
) -> bool:
    return min(first[0], second[0]) <= point[0] <= max(first[0], second[0]) and min(
        first[1], second[1]
    ) <= point[1] <= max(first[1], second[1])


def _segments_intersect(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
    fourth: tuple[float, float],
) -> bool:
    orientations = (
        _orientation(first, second, third),
        _orientation(first, second, fourth),
        _orientation(third, fourth, first),
        _orientation(third, fourth, second),
    )
    if (orientations[0] > 0) != (orientations[1] > 0) and (orientations[2] > 0) != (
        orientations[3] > 0
    ):
        return True
    return any(
        orientation == 0 and _on_segment(start, end, point)
        for orientation, start, end, point in (
            (orientations[0], first, second, third),
            (orientations[1], first, second, fourth),
            (orientations[2], third, fourth, first),
            (orientations[3], third, fourth, second),
        )
    )


def _polygons_intersect(
    first: tuple[tuple[float, float], ...],
    second: tuple[tuple[float, float], ...],
) -> bool:
    if any(
        _point_in_ring(latitude, longitude, second) for latitude, longitude in first
    ):
        return True
    if any(
        _point_in_ring(latitude, longitude, first) for latitude, longitude in second
    ):
        return True
    first_edges = zip(first, first[1:] + first[:1], strict=True)
    second_edges = zip(second, second[1:] + second[:1], strict=True)
    return any(
        _segments_intersect(first_start, first_end, second_start, second_end)
        for first_start, first_end in first_edges
        for second_start, second_end in second_edges
    )
