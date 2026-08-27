"""Earthquake event identity, ranking, and ambiguity policy."""

from dataclasses import replace
from datetime import datetime

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.event_identity import (
    distance_km,
    distance_to_coordinates,
    measurement,
    provider_identifiers,
)
from disaster_monitor.application.services.event_resolution_core import (
    BaseEventPolicy,
    EventResolution,
    location_matches,
)
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    EarthquakeEvent,
    MeasurementKind,
)


def _is_aftershock(event: DisasterEvent) -> bool:
    return isinstance(event, EarthquakeEvent) and event.is_aftershock


def _intensity_score(value: float | str | None) -> float:
    if not value:
        return 0.0
    if not isinstance(value, str):
        return float(value)
    normalized = (
        value.lower().translate(str.maketrans("０１２３４５６７", "01234567")).strip()
    )
    for token, score in (
        ("7", 7.0),
        ("6+", 6.0),
        ("6-", 5.5),
        ("5+", 5.0),
        ("5-", 4.5),
        ("4", 4.0),
        ("3", 3.0),
        ("2", 2.0),
        ("1", 1.0),
    ):
        if token in normalized:
            return score
    return 0.0


class EarthquakeEventPolicy(BaseEventPolicy):
    """Earthquake mainshock, equivalence, ranking, and ambiguity policy."""

    def _merge_event(self, events: list[DisasterEvent]) -> DisasterEvent:
        merged = super()._merge_event(events)
        earthquakes = [event for event in events if isinstance(event, EarthquakeEvent)]
        if not earthquakes or not isinstance(merged, EarthquakeEvent):
            return merged
        return replace(
            merged,
            is_aftershock=any(event.is_aftershock for event in earthquakes),
            parent_event_id=next(
                (
                    event.parent_event_id
                    for event in earthquakes
                    if event.parent_event_id
                ),
                None,
            ),
            sequence_id=next(
                (event.sequence_id for event in earthquakes if event.sequence_id),
                None,
            ),
        )

    def rank(self, event: DisasterEvent, query: DisasterQuery, now: datetime) -> float:
        age_hours = max(0.0, (now - event.event_time).total_seconds() / 3600)
        recency = max(0.0, 1.0 - age_hours / (30 * 24))
        discriminator_bonus = 0.0
        if query.prefecture and location_matches(event, query.prefecture):
            discriminator_bonus += 8.0
        if query.city and location_matches(event, query.city):
            discriminator_bonus += 8.0
        if query.latitude is not None and query.longitude is not None:
            distance = distance_to_coordinates(event, query.latitude, query.longitude)
            if distance is not None:
                discriminator_bonus += max(0.0, 8.0 - distance / 25.0)
        query_magnitude = query.discriminator("magnitude")
        magnitude = measurement(event, MeasurementKind.MAGNITUDE)
        if query_magnitude is not None and isinstance(magnitude, (int, float)):
            discriminator_bonus += max(
                0.0, 4.0 - abs(magnitude - float(query_magnitude)) * 8
            )
        significance = measurement(event, MeasurementKind.PROVIDER_SIGNIFICANCE)
        return (
            recency * 0.6
            + (magnitude if isinstance(magnitude, (int, float)) else 0.0) * 2.0
            + _intensity_score(measurement(event, MeasurementKind.INTENSITY)) * 1.5
            + (significance if isinstance(significance, (int, float)) else 0.0) / 500
            + discriminator_bonus
            - (3.0 if _is_aftershock(event) else 0.0)
        )

    def same_physical_event(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        if (
            first.disaster != second.disaster
            or first.country.alpha3_code != second.country.alpha3_code
        ):
            return False
        if (
            provider_identifiers(first) & provider_identifiers(second)
            and abs((first.event_time - second.event_time).total_seconds()) <= 24 * 3600
        ):
            return True
        if super().same_physical_event(first, second):
            return True
        if abs((first.event_time - second.event_time).total_seconds()) > 90:
            return False
        distance = distance_km(first, second)
        if distance is None or distance > 30:
            return False
        first_magnitude = measurement(first, MeasurementKind.MAGNITUDE)
        second_magnitude = measurement(second, MeasurementKind.MAGNITUDE)
        return not (
            isinstance(first_magnitude, (int, float))
            and isinstance(second_magnitude, (int, float))
            and abs(first_magnitude - second_magnitude) > 0.5
        )

    def same_sequence(self, first: DisasterEvent, second: DisasterEvent) -> bool:
        first_ids = provider_identifiers(first)
        second_ids = provider_identifiers(second)
        if (
            isinstance(first, EarthquakeEvent)
            and first.parent_event_id
            and first.parent_event_id.lower() in second_ids
        ):
            return True
        if (
            isinstance(second, EarthquakeEvent)
            and second.parent_event_id
            and second.parent_event_id.lower() in first_ids
        ):
            return True
        if (
            isinstance(first, EarthquakeEvent)
            and isinstance(second, EarthquakeEvent)
            and first.sequence_id
            and first.sequence_id == second.sequence_id
        ):
            return True
        if not (_is_aftershock(first) or _is_aftershock(second)):
            return False
        distance = distance_km(first, second)
        return bool(
            distance is not None
            and distance <= 50
            and abs((first.event_time - second.event_time).total_seconds()) <= 48 * 3600
        )

    def _filtered(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        now: datetime,
    ) -> list[DisasterEvent]:
        filtered = super()._filtered(candidates, query, now)
        query_magnitude = query.discriminator("magnitude")
        if query_magnitude is not None:
            filtered = [
                event
                for event in filtered
                if isinstance(
                    magnitude := measurement(event, MeasurementKind.MAGNITUDE),
                    (int, float),
                )
                and abs(magnitude - float(query_magnitude)) <= 0.25
            ]
        return filtered

    def describe_selection(self, query: DisasterQuery, ambiguous: bool) -> str:
        if ambiguous:
            return (
                "Multiple unrelated earthquake candidates have materially similar "
                "recency and significance."
            )
        if any(
            (
                query.discriminator("event_id"),
                query.date_from,
                query.date_to,
                query.prefecture,
                query.city,
                query.latitude is not None and query.longitude is not None,
                query.discriminator("magnitude") is not None,
            )
        ):
            return (
                "Selected the earthquake matching the explicit date, location, "
                "coordinate, magnitude, or event-identifier discriminator."
            )
        return (
            "Selected the highest-ranked recent earthquake using intensity, "
            "magnitude, provider significance, recency, and an aftershock penalty."
        )

    def resolve(
        self,
        candidates: tuple[DisasterEvent, ...],
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> EventResolution:
        resolution = super().resolve(candidates, query, now=now)
        if resolution.selected is None or not resolution.alternatives:
            return resolution
        second = resolution.alternatives[0]
        ambiguous = resolution.ambiguous or (
            not self.same_sequence(resolution.selected, second)
            and (
                self.rank(resolution.selected, query, now)
                - self.rank(second, query, now)
                < self.ambiguity_threshold
                or _is_aftershock(second)
            )
        )
        return replace(
            resolution,
            ambiguous=ambiguous,
            rationale=self.describe_selection(query, ambiguous),
        )
