"""NASA FIRMS event-associated satellite observation evidence."""

import csv
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from math import asin, cos, isfinite, radians, sin, sqrt
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    Disaster,
    DisasterEvent,
    EventGeometryKind,
    FactStatus,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_text,
)

_FIRMS_API_ROOT = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
_FIRMS_CANONICAL_URL = "https://firms.modaps.eosdis.nasa.gov/map/"
_FIRMS_PRODUCT = "VIIRS_SNPP_NRT"
_OBSERVATION_RADIUS_KM = 50.0
_DAY_RANGE = 3
_MAX_OBSERVATIONS = 500
_MAP_KEY = re.compile(r"^[A-Za-z0-9_-]{8,200}$")


@dataclass(frozen=True, slots=True)
class _Detection:
    latitude: float
    longitude: float
    observed_at: datetime


class NasaFirmsObservationAdapter:
    """Attach nearby FIRMS detections as possible observations, never events."""

    provider_name = "NASA FIRMS observations"
    source_id = "nasa-firms-observations"
    allowed_hosts = frozenset({"firms.modaps.eosdis.nasa.gov"})

    def __init__(
        self,
        *,
        map_key: SecretStr | str | None = None,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        raw_key = (
            map_key.get_secret_value() if isinstance(map_key, SecretStr) else map_key
        )
        normalized_key = (raw_key or "").strip()
        self._map_key = normalized_key if _MAP_KEY.fullmatch(normalized_key) else None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._max_response_bytes = max_response_bytes

    @property
    def configured(self) -> bool:
        return self._map_key is not None

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        if (
            not self.configured
            or query.disaster is not Disaster.WILDFIRE
            or event.disaster is not Disaster.WILDFIRE
        ):
            return ProviderBatch()
        if event.country.alpha3_code != query.country.alpha3_code:
            return ProviderBatch()
        return await self._get_reports(
            event,
            now=now,
            country_codes=(query.country.alpha3_code,),
            countries=(query.country.canonical_name,),
        )

    async def get_worldwide_situation_reports(
        self,
        event: WorldwideDisasterEvent,
        query: WorldwideDisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        if (
            not self.configured
            or query.disaster is not Disaster.WILDFIRE
            or event.disaster is not Disaster.WILDFIRE
        ):
            return ProviderBatch()
        return await self._get_reports(event, now=now, country_codes=(), countries=())

    async def _get_reports(
        self,
        event: DisasterEvent | WorldwideDisasterEvent,
        *,
        now: datetime,
        country_codes: tuple[str, ...],
        countries: tuple[str, ...],
    ) -> ProviderBatch[SituationReport]:
        point = _event_point(event)
        if point is None:
            return ProviderBatch(issues=(_geometry_unavailable(),))
        latitude, longitude = point
        start_date = now.astimezone(UTC).date() - timedelta(days=_DAY_RANGE - 1)
        detections: set[_Detection] = set()
        issues: list[ProviderIssue] = []
        contributing_snapshot_ids: list[str] = []
        row_index = 0
        limit_reached = False
        for bbox in _bboxes(latitude, longitude):
            endpoint = (
                f"{_FIRMS_API_ROOT}/{quote(self._map_key or '', safe='')}/"
                f"{_FIRMS_PRODUCT}/{bbox}/{_DAY_RANGE}/{start_date.isoformat()}"
            )
            capture = build_snapshot_capture(
                self._snapshot_recorder,
                source_id=self.source_id,
                parameters={
                    "event": event.event_id,
                    "product": _FIRMS_PRODUCT,
                    "bbox": bbox,
                    "start": start_date.isoformat(),
                    "days": str(_DAY_RANGE),
                },
                rights_id="nasa-earth-science-data-use",
                retrieved_at=now,
            )
            payload = await get_text(
                self._client,
                endpoint,
                allowed_hosts=self.allowed_hosts,
                max_bytes=self._max_response_bytes,
                provider_name=self.provider_name,
                capture=capture,
            )
            reader = csv.DictReader(StringIO(payload))
            if reader.fieldnames is None or not {
                "latitude",
                "longitude",
                "acq_date",
                "acq_time",
            }.issubset(reader.fieldnames):
                issues.append(_invalid_schema())
                continue
            previous_count = len(detections)
            for row in reader:
                index = row_index
                row_index += 1
                try:
                    detection = _parse_detection(row)
                except (TypeError, ValueError, OverflowError) as error:
                    issues.append(_invalid_record(index, error))
                    continue
                if (
                    _distance_km(
                        latitude,
                        longitude,
                        detection.latitude,
                        detection.longitude,
                    )
                    <= _OBSERVATION_RADIUS_KM
                ):
                    detections.add(detection)
                if len(detections) >= _MAX_OBSERVATIONS:
                    issues.append(_observation_limit())
                    limit_reached = True
                    break
            if len(detections) > previous_count and capture and capture.snapshot:
                contributing_snapshot_ids.append(capture.snapshot.snapshot_id)
            if limit_reached:
                break
        if not detections:
            if not issues:
                issues.append(_empty_result())
            return ProviderBatch(issues=tuple(issues))
        ordered_detections = sorted(
            detections,
            key=lambda item: (item.observed_at, item.latitude, item.longitude),
        )
        earliest = ordered_detections[0].observed_at
        latest = ordered_detections[-1].observed_at
        source = SourceReference(
            source_id=self.source_id,
            publisher="NASA Fire Information for Resource Management System (FIRMS)",
            title="VIIRS near-real-time fire and thermal anomaly observations",
            canonical_url=_FIRMS_CANONICAL_URL,
            published_at=None,
            updated_at=latest,
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
            snapshot_id=(
                contributing_snapshot_ids[0] if contributing_snapshot_ids else None
            ),
        )
        facts = (
            ReportedFact(
                category="satellite_observation",
                label="Nearby thermal anomaly detections",
                value=str(len(ordered_detections)),
                status=FactStatus.PRELIMINARY,
                source=source,
                event_id=event.event_id,
                observed_at=latest,
            ),
            ReportedFact(
                category="satellite_observation",
                label="Observation interval (UTC)",
                value=f"{earliest.isoformat()} to {latest.isoformat()}",
                status=FactStatus.PRELIMINARY,
                source=source,
                event_id=event.event_id,
                observed_at=latest,
            ),
        )
        report = SituationReport(
            source=source,
            narrative=(
                f"NASA FIRMS reported {len(ordered_detections)} VIIRS fire/thermal "
                "anomaly "
                f"detections within {_OBSERVATION_RADIUS_KM:.0f} km of the selected "
                "event point. These satellite pixels are possible observations only: "
                "they do not confirm wildfire identity, ignition, perimeter, size, "
                "impact, or containment, and can include other heat sources."
            ),
            facts=facts,
            event_id=event.event_id,
            correlation=CorrelationStatus.POSSIBLE,
            reported_event_time=latest,
            locations=(event.location,),
            countries=countries,
            country_codes=country_codes,
            disaster=Disaster.WILDFIRE,
        )
        return ProviderBatch((report,), tuple(issues))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _event_point(
    event: DisasterEvent | WorldwideDisasterEvent,
) -> tuple[float, float] | None:
    geometry = event.geometry
    if (
        geometry is None
        or geometry.kind is not EventGeometryKind.POINT
        or len(geometry.coordinates) != 1
    ):
        return None
    point = geometry.coordinates[0]
    return point.latitude, point.longitude


def _bboxes(latitude: float, longitude: float) -> tuple[str, ...]:
    latitude_delta = _OBSERVATION_RADIUS_KM / 111.0
    longitude_scale = max(cos(radians(latitude)), 0.1)
    longitude_delta = _OBSERVATION_RADIUS_KM / (111.0 * longitude_scale)
    south = max(-90.0, latitude - latitude_delta)
    north = min(90.0, latitude + latitude_delta)
    west = longitude - longitude_delta
    east = longitude + longitude_delta
    boxes: tuple[tuple[float, float, float, float], ...]
    if west < -180.0:
        boxes = (
            (-180.0, south, east, north),
            (west + 360.0, south, 180.0, north),
        )
    elif east > 180.0:
        boxes = (
            (west, south, 180.0, north),
            (-180.0, south, east - 360.0, north),
        )
    else:
        boxes = ((west, south, east, north),)
    return tuple(",".join(f"{value:.5f}" for value in bounds) for bounds in boxes)


def _parse_detection(row: dict[str, str]) -> _Detection:
    latitude = float(row["latitude"])
    longitude = float(row["longitude"])
    if (
        not isfinite(latitude)
        or not isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("coordinates are invalid")
    raw_time = row["acq_time"].strip().zfill(4)
    if len(raw_time) != 4 or not raw_time.isdigit():
        raise ValueError("acquisition time is invalid")
    timestamp = normalize_timestamp(
        f"{date.fromisoformat(row['acq_date'].strip()).isoformat()}T"
        f"{raw_time[:2]}:{raw_time[2:]}:00Z"
    )
    if timestamp is None:
        raise ValueError("acquisition timestamp is invalid")
    return _Detection(latitude, longitude, timestamp)


def _distance_km(
    first_latitude: float,
    first_longitude: float,
    second_latitude: float,
    second_longitude: float,
) -> float:
    latitude_delta = radians(second_latitude - first_latitude)
    longitude_delta = radians(second_longitude - first_longitude)
    start_latitude = radians(first_latitude)
    end_latitude = radians(second_latitude)
    value = sin(latitude_delta / 2) ** 2 + (
        cos(start_latitude) * cos(end_latitude) * sin(longitude_delta / 2) ** 2
    )
    return 2 * 6_371.0088 * asin(min(1.0, sqrt(value)))


def _geometry_unavailable() -> ProviderIssue:
    return ProviderIssue(
        NasaFirmsObservationAdapter.provider_name,
        "NASA FIRMS observations: The selected event has no source-backed point "
        "for a bounded observation query.",
        reason_code="event_geometry_unavailable",
    )


def _invalid_schema() -> ProviderIssue:
    return ProviderIssue(
        NasaFirmsObservationAdapter.provider_name,
        "NASA FIRMS observations: The CSV response had no supported detection fields.",
        reason_code="invalid_schema",
    )


def _invalid_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        NasaFirmsObservationAdapter.provider_name,
        "NASA FIRMS observations: A malformed detection was skipped.",
        reason_code="invalid_record",
        detail=f"row[{index}]: {error}",
    )


def _observation_limit() -> ProviderIssue:
    return ProviderIssue(
        NasaFirmsObservationAdapter.provider_name,
        "NASA FIRMS observations: The bounded observation limit was reached.",
        reason_code="result_limit_reached",
    )


def _empty_result() -> ProviderIssue:
    return ProviderIssue(
        NasaFirmsObservationAdapter.provider_name,
        "NASA FIRMS observations: No nearby thermal anomaly observations were found.",
        reason_code="empty_result",
    )
