"""NASA EONET wildfire event discovery through the v3 events API."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from urllib.parse import quote

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventCoordinate,
    EventGeographyStatus,
    EventGeometry,
    EventGeometryKind,
    EventMeasurement,
    MeasurementKind,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_json,
)

EONET_EVENTS_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
_EONET_EVENT_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
_EONET_RIGHTS_ID = "nasa-eonet-api"
_MAX_TIME_WINDOW_DAYS = 30
_MAX_EVENTS = 50
_WILDFIRE_CATEGORY = "wildfires"


@dataclass(frozen=True, slots=True)
class _Observation:
    observed_at: datetime
    geometry: EventGeometry
    magnitude_value: float | int | None
    magnitude_unit: str | None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is not an object")
    return value


def _strict_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is missing")
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} is not timezone-aware")
    return parsed.astimezone(UTC)


def _number(value: object) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not isfinite(float(value)):
        return None
    return value


def _time_window(
    query: DisasterQuery | WorldwideDisasterQuery, *, now: datetime
) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The provider clock must be timezone-aware")
    end = (query.date_to if isinstance(query, DisasterQuery) else None) or now
    start = (
        query.date_from if isinstance(query, DisasterQuery) else None
    ) or now - timedelta(days=max(1, query.time_window_days))
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if end < start:
        raise ValueError("The query time window is inverted")
    if end - start > timedelta(days=_MAX_TIME_WINDOW_DAYS):
        start = end - timedelta(days=_MAX_TIME_WINDOW_DAYS)
    return start, end


def _category_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("categories are missing")
    identifiers: list[str] = []
    for item in value:
        category = _mapping(item, "category")
        identifier = _text(category.get("id"))
        if identifier:
            identifiers.append(identifier.casefold())
    return tuple(identifiers)


def _coordinate(value: object, label: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} is missing")
    if len(value) < 2:
        raise ValueError(f"{label} is incomplete")
    longitude, latitude = value[0], value[1]
    if (
        isinstance(longitude, bool)
        or isinstance(latitude, bool)
        or not isinstance(longitude, (int, float))
        or not isinstance(latitude, (int, float))
        or not isfinite(float(longitude))
        or not isfinite(float(latitude))
        or not -180 <= float(longitude) <= 180
        or not -90 <= float(latitude) <= 90
    ):
        raise ValueError(f"{label} is outside WGS84")
    return float(latitude), float(longitude)


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


class NasaEonetWildfireAdapter:
    """Discover source-backed wildfires from NASA's curated EONET registry."""

    provider_name = "NASA EONET Wildfires"
    source_id = "nasa-eonet-wildfires"
    allowed_hosts = frozenset({"eonet.gsfc.nasa.gov"})

    def __init__(
        self,
        *,
        geography: CountryCatalog | None = None,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._geography = geography
        self._snapshot_recorder = snapshot_recorder
        self._max_response_bytes = max_response_bytes

    def _parse_event(
        self,
        raw_event: object,
        *,
        now: datetime,
        start: datetime,
        end: datetime,
        index: int,
        country: Country | None,
        snapshot_id: str | None,
    ) -> tuple[
        WorldwideDisasterEvent | DisasterEvent | None, tuple[ProviderIssue, ...]
    ]:
        try:
            event = _mapping(raw_event, "event")
            if _WILDFIRE_CATEGORY not in _category_ids(event.get("categories")):
                return None, ()
            raw_id = _text(event.get("id"))
            location = _text(event.get("title")) or _text(event.get("description"))
            if not raw_id or not location:
                raise ValueError("event identifier or title is missing")
            raw_geometry = event.get("geometry")
            if not isinstance(raw_geometry, list):
                raise ValueError("geometry list is missing")
        except (TypeError, ValueError) as error:
            return None, (_invalid_record(index, error),)

        observations: list[_Observation] = []
        issues: list[ProviderIssue] = []
        for geometry_index, raw_observation in enumerate(raw_geometry):
            try:
                observation = _parse_observation(raw_observation)
                observations.append(observation)
            except (TypeError, ValueError) as error:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        f"{self.provider_name}: A malformed geometry observation "
                        "was skipped.",
                        reason_code="invalid_geometry",
                        detail=f"event[{index}].geometry[{geometry_index}]: {error}",
                    )
                )
        if not observations:
            return None, (
                _invalid_record(index, ValueError("no valid dated geometry")),
            )

        relevant_observations = tuple(
            observation
            for observation in observations
            if start <= observation.observed_at <= end
        )
        if not relevant_observations:
            return None, (
                _invalid_record(
                    index,
                    ValueError("no valid geometry in the bounded query window"),
                ),
            )

        selected = max(
            (
                observation
                for observation in relevant_observations
                if _observation_matches_country(observation, country, self._geography)
            ),
            key=lambda observation: observation.observed_at,
            default=None,
        )
        if country is not None and selected is None:
            return None, (
                *issues,
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: An event outside "
                    f"{country.canonical_name} was excluded.",
                    reason_code="country_mismatch",
                    detail=f"event[{index}] geometry failed country validation",
                ),
            )
        selected = selected or max(
            relevant_observations, key=lambda observation: observation.observed_at
        )
        event_time = min(observation.observed_at for observation in observations)
        updated_at = max(observation.observed_at for observation in observations)
        canonical_url = f"{_EONET_EVENT_URL}/{quote(raw_id, safe='')}"
        source = SourceReference(
            source_id=self.source_id,
            publisher="NASA Earth Observatory Natural Event Tracker (EONET)",
            title=location,
            canonical_url=canonical_url,
            published_at=event_time,
            updated_at=updated_at,
            retrieved_at=now.astimezone(UTC),
            authority=SourceAuthority.SECONDARY,
            snapshot_id=snapshot_id,
        )
        selected_geometry = replace(selected.geometry, source=source)
        provider_ids = (f"eonet:{raw_id}", *_source_ids(event.get("sources")))
        measurements = (
            (
                EventMeasurement(
                    MeasurementKind.MAGNITUDE,
                    selected.magnitude_value,
                    selected.magnitude_unit,
                    source=source,
                ),
            )
            if selected.magnitude_value is not None and selected.magnitude_unit
            else ()
        )
        if country is None:
            return (
                WorldwideDisasterEvent(
                    event_id=f"eonet:{raw_id}",
                    disaster=Disaster.WILDFIRE,
                    location=location,
                    event_time=event_time,
                    source=source,
                    geometry=selected_geometry,
                    measurements=measurements,
                    provider_ids=provider_ids,
                ),
                tuple(issues),
            )
        return (
            DisasterEvent(
                event_id=f"eonet:{raw_id}",
                disaster=Disaster.WILDFIRE,
                location=location,
                country=country,
                event_time=event_time,
                source=source,
                geometry=selected_geometry,
                measurements=measurements,
                provider_ids=provider_ids,
                geography_status=EventGeographyStatus.IN_COUNTRY,
            ),
            tuple(issues),
        )

    async def _find(
        self,
        query: DisasterQuery | WorldwideDisasterQuery,
        *,
        now: datetime,
        country: Country | None,
    ) -> ProviderBatch[WorldwideDisasterEvent | DisasterEvent]:
        try:
            start, end = _time_window(query, now=now)
        except ValueError as error:
            return ProviderBatch(issues=(_invalid_query(error),))
        params: dict[str, str | int] = {
            "category": _WILDFIRE_CATEGORY,
            "status": "all",
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "limit": min(_MAX_EVENTS, max(1, query.limit))
            if isinstance(query, WorldwideDisasterQuery)
            else _MAX_EVENTS,
        }
        if country is not None:
            area = country.geographic_area
            params["bbox"] = ",".join(
                str(value)
                for value in (
                    area.min_longitude,
                    area.max_latitude,
                    area.max_longitude,
                    area.min_latitude,
                )
            )
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={key: str(value) for key, value in params.items()},
            rights_id=_EONET_RIGHTS_ID,
            retrieved_at=now.astimezone(UTC),
        )
        payload = await get_json(
            self._client,
            EONET_EVENTS_URL,
            params=params,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
            accepted_content_types=frozenset({"application/rss+xml"}),
        )
        response = _mapping(payload, "EONET response")
        raw_events = response.get("events")
        if not isinstance(raw_events, list):
            raise DisasterProviderResponseError(
                "The EONET response had no event list.", reason_code="invalid_schema"
            )
        records: list[WorldwideDisasterEvent | DisasterEvent] = []
        issues: list[ProviderIssue] = []
        snapshot_id = (
            capture.snapshot.snapshot_id if capture and capture.snapshot else None
        )
        result_limit = (
            min(_MAX_EVENTS, max(1, query.limit))
            if isinstance(query, WorldwideDisasterQuery)
            else _MAX_EVENTS
        )
        for index, raw_event in enumerate(raw_events[:result_limit]):
            record, event_issues = self._parse_event(
                raw_event,
                now=now,
                start=start,
                end=end,
                index=index,
                country=country,
                snapshot_id=snapshot_id,
            )
            if record is not None:
                records.append(record)
            issues.extend(event_issues)
        records, duplicate_issues = _deduplicate_records(records)
        issues.extend(duplicate_issues)
        if not records and not issues:
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: The provider returned no matching records.",
                    reason_code="empty_result",
                )
            )
        return ProviderBatch(tuple(records), tuple(issues))

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if (
            not isinstance(query, DisasterQuery)
            or query.disaster is not Disaster.WILDFIRE
        ):
            return ProviderBatch()
        result = await self._find(query, now=now, country=query.country)
        return ProviderBatch(
            records=tuple(
                item for item in result.records if isinstance(item, DisasterEvent)
            ),
            issues=result.issues,
        )

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[WorldwideDisasterEvent]:
        if (
            not isinstance(query, WorldwideDisasterQuery)
            or query.disaster is not Disaster.WILDFIRE
        ):
            return ProviderBatch()
        result = await self._find(query, now=now, country=None)
        return ProviderBatch(
            records=tuple(
                item
                for item in result.records
                if isinstance(item, WorldwideDisasterEvent)
            ),
            issues=result.issues,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _parse_observation(raw_observation: object) -> _Observation:
    observation = _mapping(raw_observation, "geometry observation")
    observed_at = _strict_timestamp(observation.get("date"), "geometry date")
    geometry_type = _text(observation.get("type"))
    raw_coordinates = observation.get("coordinates")
    if geometry_type == "Point":
        latitude, longitude = _coordinate(raw_coordinates, "point coordinates")
        geometry = point_event_geometry(
            latitude,
            longitude,
            SourceReference(
                source_id="nasa-eonet-wildfires",
                publisher="NASA Earth Observatory Natural Event Tracker (EONET)",
                title="EONET geometry",
                canonical_url=EONET_EVENTS_URL,
                published_at=observed_at,
                updated_at=observed_at,
                retrieved_at=observed_at,
            ),
        )
    elif geometry_type == "Polygon":
        if not isinstance(raw_coordinates, list) or len(raw_coordinates) != 1:
            raise ValueError("polygon must contain one representable outer ring")
        raw_ring = raw_coordinates[0]
        if not isinstance(raw_ring, list) or len(raw_ring) < 3:
            raise ValueError("polygon ring is incomplete")
        coordinates = tuple(
            _coordinate(item, "polygon coordinate") for item in raw_ring
        )
        geometry = EventGeometry(
            kind=EventGeometryKind.AREA,
            source=SourceReference(
                source_id="nasa-eonet-wildfires",
                publisher="NASA Earth Observatory Natural Event Tracker (EONET)",
                title="EONET geometry",
                canonical_url=EONET_EVENTS_URL,
                published_at=observed_at,
                updated_at=observed_at,
                retrieved_at=observed_at,
            ),
            coordinates=tuple(
                EventCoordinate(latitude, longitude)
                for latitude, longitude in coordinates
            ),
        )
    else:
        raise ValueError("geometry type is unsupported")
    value = _number(observation.get("magnitudeValue"))
    unit = _text(observation.get("magnitudeUnit")) or None
    return _Observation(observed_at, geometry, value, unit)


def _source_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    identifiers: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        identifier = _text(item.get("id"))
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    return tuple(sorted(identifiers))


def _deduplicate_records(
    records: list[WorldwideDisasterEvent | DisasterEvent],
) -> tuple[
    list[WorldwideDisasterEvent | DisasterEvent],
    tuple[ProviderIssue, ...],
]:
    unique: dict[str, WorldwideDisasterEvent | DisasterEvent] = {}
    conflicting: set[str] = set()
    issues: list[ProviderIssue] = []
    for index, record in enumerate(records):
        if record.event_id in conflicting:
            continue
        previous = unique.get(record.event_id)
        if previous is None:
            unique[record.event_id] = record
            continue
        if previous == record:
            continue
        del unique[record.event_id]
        conflicting.add(record.event_id)
        issues.append(
            ProviderIssue(
                NasaEonetWildfireAdapter.provider_name,
                f"{NasaEonetWildfireAdapter.provider_name}: Conflicting duplicate "
                "event identities were excluded.",
                reason_code="duplicate_identity",
                detail=f"normalized event {record.event_id!r} at record {index}",
            )
        )
    return list(unique.values()), tuple(issues)


def _observation_matches_country(
    observation: _Observation,
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
    if observation.geometry.kind is EventGeometryKind.POINT:
        point = observation.geometry.coordinates[0]
        return geography.contains(projected_country, point.latitude, point.longitude)
    event_ring = tuple(
        (point.latitude, point.longitude) for point in observation.geometry.coordinates
    )
    country_polygons = projected_country.geographic_area.polygons
    if not country_polygons:
        return any(
            geography.contains(projected_country, latitude, longitude)
            for latitude, longitude in event_ring
        )
    return any(_polygons_intersect(event_ring, polygon) for polygon in country_polygons)


def _invalid_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        NasaEonetWildfireAdapter.provider_name,
        f"{NasaEonetWildfireAdapter.provider_name}: A malformed event record "
        "was skipped.",
        reason_code="invalid_record",
        detail=f"event[{index}]: {error}",
    )


def _invalid_query(error: Exception) -> ProviderIssue:
    return ProviderIssue(
        NasaEonetWildfireAdapter.provider_name,
        f"{NasaEonetWildfireAdapter.provider_name}: The normalized query "
        "window is invalid.",
        reason_code="invalid_query",
        detail=str(error),
    )
