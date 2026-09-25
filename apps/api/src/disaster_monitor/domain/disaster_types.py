"""Disaster taxonomy and geographic value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
    DROUGHT = "drought"


class ObservationKind(StrEnum):
    """How a provider record may participate in physical-incident workflows."""

    PHYSICAL_EVENT = "physical_event"
    PRELIMINARY_EVENT = "preliminary_event"
    ACQUISITION = "acquisition"


class EventTimePrecision(StrEnum):
    """Source-backed temporal precision of a normalized event observation."""

    EXACT = "exact"
    DAY = "day"
    WEEK = "week"


def validate_event_temporality(
    event_time: datetime,
    event_time_end: datetime | None,
    event_time_precision: EventTimePrecision,
    observation_kind: ObservationKind,
) -> None:
    """Protect week observations from becoming fabricated exact events."""
    if not isinstance(event_time_precision, EventTimePrecision):
        raise TypeError("An event requires typed temporal precision.")
    if not isinstance(observation_kind, ObservationKind):
        raise TypeError("An event requires a typed observation kind.")
    if event_time_precision is EventTimePrecision.WEEK:
        if event_time_end is None:
            raise ValueError("A week-precision event requires an end date.")
        if not _is_aware(event_time) or not _is_aware(event_time_end):
            raise ValueError("A week-precision event interval must be timezone-aware.")
        if any(
            value.utcoffset() != timedelta(0)
            or any((value.hour, value.minute, value.second, value.microsecond))
            for value in (event_time, event_time_end)
        ):
            raise ValueError(
                "A week-precision event interval requires UTC calendar dates."
            )
        if event_time_end - event_time != timedelta(days=6):
            raise ValueError("A week-precision event must span seven calendar dates.")
        if observation_kind is not ObservationKind.PRELIMINARY_EVENT:
            raise ValueError(
                "A week-precision event must remain a preliminary observation."
            )
        return
    if event_time_precision is EventTimePrecision.DAY and (
        not _is_aware(event_time)
        or event_time.utcoffset() != timedelta(0)
        or any(
            (
                event_time.hour,
                event_time.minute,
                event_time.second,
                event_time.microsecond,
            )
        )
    ):
        raise ValueError("A day-precision event requires a UTC calendar date.")
    if event_time_end is not None:
        raise ValueError("Only week-precision events may carry an end date.")
    if observation_kind is ObservationKind.PRELIMINARY_EVENT:
        raise ValueError("A preliminary event requires week temporal precision.")


def event_temporality_overlaps(
    event_time: datetime,
    event_time_end: datetime | None,
    event_time_precision: EventTimePrecision,
    interval_start: datetime,
    interval_end: datetime,
) -> bool:
    """Return whether exact instants or inclusive calendar dates overlap a window."""
    if event_time_precision is EventTimePrecision.WEEK:
        if event_time_end is None:
            return False
        return (
            event_time.date() <= interval_end.date()
            and event_time_end.date() >= interval_start.date()
        )
    return interval_start <= event_time <= interval_end


class IncidentActivityStatus(StrEnum):
    """Source-backed lifecycle state; unknown is preferable to an inference."""

    ONGOING = "ongoing"
    ENDED = "ended"
    UNKNOWN = "unknown"


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

    point_x, point_y = 0.0, 0.0
    start_longitude_delta = (start_longitude - longitude + 180) % 360 - 180
    # Unwrap both endpoints as one segment; wrapping each against the query
    # separately can make a distant boundary cross the query at the dateline.
    segment_longitude_delta = (end_longitude - start_longitude + 180) % 360 - 180
    start_x = radians(start_longitude_delta) * cos(reference_latitude)
    end_x = radians(start_longitude_delta + segment_longitude_delta) * cos(
        reference_latitude
    )
    start_y = radians(start_latitude - latitude)
    end_y = radians(end_latitude - latitude)
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
