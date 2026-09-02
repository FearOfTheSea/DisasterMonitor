"""Disaster taxonomy and geographic value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class Disaster(StrEnum):
    """Disasters recognized by deterministic request parsing."""

    EARTHQUAKE = "earthquake"
    FLOOD = "flood"
    WILDFIRE = "wildfire"
    LANDSLIDE = "landslide"
    TROPICAL_CYCLONE = "tropical_cyclone"
    VOLCANIC_ERUPTION = "volcanic_eruption"


class BoundaryValidationQuality(StrEnum):
    """Strength of a geographic membership decision."""

    BOUNDING_BOX = "bounding_box"
    POLYGON = "polygon"


class EventGeographyStatus(StrEnum):
    """How a selected event relates to the requested country's land area."""

    IN_COUNTRY = "in_country"
    COUNTRY_ASSOCIATED_OFFSHORE = "country_associated_offshore"
    WORLDWIDE = "worldwide"


class ProviderTier(StrEnum):
    """Explicit authority tier assigned to a provider observation."""

    PRIMARY = "primary"
    SECONDARY = "secondary"

    @property
    def precedence(self) -> int:
        """Return the deterministic canonical-selection precedence."""
        return 2 if self is ProviderTier.PRIMARY else 1


@dataclass(frozen=True, slots=True)
class GeographicArea:
    """A bounded query area and its validation quality."""

    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    validation_quality: BoundaryValidationQuality = (
        BoundaryValidationQuality.BOUNDING_BOX
    )
    polygons: tuple[tuple[tuple[float, float], ...], ...] = ()

    def contains(self, latitude: float, longitude: float) -> bool:
        """Return whether a coordinate lies in the represented area."""
        in_bounds = (
            self.min_latitude <= latitude <= self.max_latitude
            and self.min_longitude <= longitude <= self.max_longitude
        )
        if not in_bounds or not self.polygons:
            return in_bounds
        return any(
            _point_in_polygon(latitude, longitude, polygon) for polygon in self.polygons
        )

    def distance_to_boundary_km(
        self, latitude: float, longitude: float
    ) -> float | None:
        """Return an approximate distance to the nearest polygon boundary.

        This is intentionally a bounded proximity check, not a replacement for
        polygon membership or a maritime boundary claim.  It is used only to
        identify near-shore events whose provider place text explicitly names
        the requested country.
        """
        if self.contains(latitude, longitude):
            return 0.0
        if not self.polygons:
            return None
        return min(
            _distance_to_segment_km(
                latitude,
                longitude,
                previous[0],
                previous[1],
                current[0],
                current[1],
            )
            for polygon in self.polygons
            for previous, current in zip(
                polygon, polygon[1:] + polygon[:1], strict=True
            )
        )


def _point_in_polygon(
    latitude: float,
    longitude: float,
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    """Return point membership using a deterministic ray-casting boundary test."""
    inside = False
    previous = polygon[-1]
    for current in polygon:
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


def _distance_to_segment_km(
    latitude: float,
    longitude: float,
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> float:
    """Approximate point-to-segment distance in a local equirectangular plane."""
    from math import cos, hypot, radians

    reference_latitude = radians(latitude)

    def project(point_latitude: float, point_longitude: float) -> tuple[float, float]:
        longitude_delta = (point_longitude - longitude + 180) % 360 - 180
        return (
            radians(longitude_delta) * cos(reference_latitude),
            radians(point_latitude - latitude),
        )

    point_x, point_y = 0.0, 0.0
    start_x, start_y = project(start_latitude, start_longitude)
    end_x, end_y = project(end_latitude, end_longitude)
    segment_x = end_x - start_x
    segment_y = end_y - start_y
    segment_length_squared = segment_x * segment_x + segment_y * segment_y
    if segment_length_squared == 0:
        return hypot(start_x, start_y) * 6_371.0088
    projection = max(
        0.0,
        min(
            1.0,
            ((point_x - start_x) * segment_x + (point_y - start_y) * segment_y)
            / segment_length_squared,
        ),
    )
    return (
        hypot(
            point_x - (start_x + projection * segment_x),
            point_y - (start_y + projection * segment_y),
        )
        * 6_371.0088
    )


@dataclass(frozen=True, slots=True)
class Country:
    """Canonical country metadata used by queries and provider records."""

    alpha3_code: str
    canonical_name: str
    aliases: tuple[str, ...]
    geographic_area: GeographicArea
    default_timezone: str | None = None
