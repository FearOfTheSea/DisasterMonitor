"""NOAA IBTrACS track and identity reconciliation for selected GDACS cyclones."""

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import StringIO
from math import asin, cos, isfinite, radians, sin, sqrt

import httpx

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

_ACTIVE_CSV_URL = (
    "https://www.ncei.noaa.gov/data/"
    "international-best-track-archive-for-climate-stewardship-ibtracs/"
    "v04r01/access/csv/ibtracs.ACTIVE.list.v04r01.csv"
)
_GDACS_SOURCE_ID = "gdacs-tropical-cyclones"
_MAX_START_DIFFERENCE = timedelta(hours=36)
_MAX_TRACK_DISTANCE_KM = 500.0
_MAX_ROWS = 5_000
_MAX_TRACK_POINTS = 500
_SUPPORTED_TRACK_TYPES = frozenset({"MAIN", "PROVISIONAL", "US-PROVISIONAL"})
_GENERIC_NAMES = frozenset({"", "INVEST", "NOTNAMED", "NONAME", "UNKNOWN", "UNNAMED"})


@dataclass(frozen=True, slots=True)
class _TrackPoint:
    observed_at: datetime
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class _Track:
    sid: str
    name: str
    track_type: str
    points: tuple[_TrackPoint, ...]
    agencies: tuple[str, ...]
    atcf_ids: tuple[str, ...]

    @property
    def start(self) -> datetime:
        return self.points[0].observed_at

    @property
    def end(self) -> datetime:
        return self.points[-1].observed_at


class IbtracsTrackAdapter:
    """Reconcile an active IBTrACS track with a selected GDACS cyclone."""

    provider_name = "NOAA IBTrACS track reconciliation"
    source_id = "noaa-ibtracs-tracks"
    allowed_hosts = frozenset({"www.ncei.noaa.gov"})

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._max_response_bytes = max_response_bytes

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        if not _eligible(event, query.disaster):
            return ProviderBatch()
        if event.country.alpha3_code != query.country.alpha3_code:
            return ProviderBatch()
        return await self._get_reports(
            event,
            now=now,
            countries=(query.country.canonical_name,),
            country_codes=(query.country.alpha3_code,),
        )

    async def get_worldwide_situation_reports(
        self,
        event: WorldwideDisasterEvent,
        query: WorldwideDisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        if not _eligible(event, query.disaster):
            return ProviderBatch()
        return await self._get_reports(
            event,
            now=now,
            countries=(),
            country_codes=(),
        )

    async def _get_reports(
        self,
        event: DisasterEvent | WorldwideDisasterEvent,
        *,
        now: datetime,
        countries: tuple[str, ...],
        country_codes: tuple[str, ...],
    ) -> ProviderBatch[SituationReport]:
        point = _event_point(event)
        if point is None:
            return ProviderBatch(issues=(_geometry_unavailable(),))
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"subset": "ACTIVE", "version": "v04r01"},
            rights_id="noaa-ncei-data",
            retrieved_at=now,
        )
        payload = await get_text(
            self._client,
            _ACTIVE_CSV_URL,
            capture=capture,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
        )
        tracks, issues = _parse_tracks(payload)
        selected_name_tokens = _name_tokens(event.source.title)
        matches: list[tuple[_Track, float]] = []
        for track in tracks:
            normalized_name = _normalized_name(track.name)
            if (
                normalized_name in _GENERIC_NAMES
                or normalized_name not in selected_name_tokens
                or abs(track.start - event.event_time) > _MAX_START_DIFFERENCE
            ):
                continue
            distance = min(
                _distance_km(point[0], point[1], item.latitude, item.longitude)
                for item in track.points
            )
            if distance <= _MAX_TRACK_DISTANCE_KM:
                matches.append((track, distance))
        matches.sort(
            key=lambda item: (
                abs(item[0].start - event.event_time),
                item[1],
                item[0].sid,
            )
        )
        if len(matches) != 1:
            issues.append(_identity_not_reconciled(ambiguous=len(matches) > 1))
            return ProviderBatch(issues=tuple(issues))

        track, distance = matches[0]
        agency_text = ", ".join(track.agencies) if track.agencies else "not stated"
        publisher = "NOAA National Centers for Environmental Information (IBTrACS)"
        if track.agencies:
            publisher = f"{publisher}; contributing track agencies: {agency_text}"
        source = SourceReference(
            source_id=self.source_id,
            publisher=publisher,
            title=f"IBTrACS {track.track_type.lower()} track for {track.name}",
            canonical_url=_ACTIVE_CSV_URL,
            published_at=None,
            updated_at=track.end,
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
            snapshot_id=capture.snapshot.snapshot_id
            if capture and capture.snapshot
            else None,
        )
        facts = (
            ReportedFact(
                category="map_layers",
                label="IBTrACS storm identifier",
                value=track.sid,
                status=FactStatus.PRELIMINARY,
                source=source,
                event_id=event.event_id,
                observed_at=track.end,
            ),
            ReportedFact(
                category="map_layers",
                label="Retained track interval (UTC)",
                value=f"{track.start.isoformat()} to {track.end.isoformat()}",
                status=FactStatus.PRELIMINARY,
                source=source,
                event_id=event.event_id,
                observed_at=track.end,
            ),
            ReportedFact(
                category="map_layers",
                label="Retained track points",
                value=str(len(track.points)),
                status=FactStatus.PRELIMINARY,
                source=source,
                event_id=event.event_id,
                observed_at=track.end,
            ),
        )
        provider_ids = (f"ibtracs:{track.sid}",) + tuple(
            f"atcf:{identifier}" for identifier in track.atcf_ids
        )
        report = SituationReport(
            source=source,
            narrative=(
                f"NOAA IBTrACS {track.track_type.lower()} track {track.sid} was "
                "reconciled to the selected GDACS cyclone by storm name, track start, "
                f"and track proximity (closest retained point {distance:.0f} km). "
                "IBTrACS is a merged best-track archive, not an independent live-event "
                "authority; contributing agency data can overlap the GDACS upstream "
                "source, and provisional points can be revised."
            ),
            facts=facts,
            event_id=event.event_id,
            correlation=CorrelationStatus.MATCHED,
            reported_event_time=track.start,
            locations=(event.location,),
            countries=countries,
            country_codes=country_codes,
            disaster=Disaster.TROPICAL_CYCLONE,
            provider_event_ids=provider_ids,
        )
        return ProviderBatch((report,), tuple(issues))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _eligible(
    event: DisasterEvent | WorldwideDisasterEvent,
    query_disaster: Disaster,
) -> bool:
    return (
        query_disaster is Disaster.TROPICAL_CYCLONE
        and event.disaster is Disaster.TROPICAL_CYCLONE
        and event.source.source_id == _GDACS_SOURCE_ID
    )


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


def _parse_tracks(payload: str) -> tuple[tuple[_Track, ...], list[ProviderIssue]]:
    reader = csv.DictReader(StringIO(payload))
    required = {
        "SID",
        "NAME",
        "ISO_TIME",
        "LAT",
        "LON",
        "TRACK_TYPE",
        "WMO_AGENCY",
        "USA_AGENCY",
        "USA_ATCF_ID",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        return (), [_invalid_schema()]
    grouped: dict[
        str,
        dict[str, object],
    ] = {}
    issues: list[ProviderIssue] = []
    for index, row in enumerate(reader):
        if index >= _MAX_ROWS:
            issues.append(_row_limit())
            break
        if not _text(row.get("SID")):
            continue
        try:
            sid = _identifier(row.get("SID"))
            name = _text(row.get("NAME"))
            track_type = _text(row.get("TRACK_TYPE")).upper()
            observed_at = normalize_timestamp(row.get("ISO_TIME"))
            latitude = float(_text(row.get("LAT")))
            longitude = float(_text(row.get("LON")))
            if (
                not sid
                or not name
                or observed_at is None
                or track_type not in _SUPPORTED_TRACK_TYPES
                or not isfinite(latitude)
                or not isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                raise ValueError("required track fields are invalid")
        except (TypeError, ValueError, OverflowError) as error:
            issues.append(_invalid_record(index, error))
            continue
        group = grouped.setdefault(
            sid,
            {
                "name": name,
                "track_type": track_type,
                "points": [],
                "agencies": set(),
                "atcf_ids": set(),
            },
        )
        if group["name"] != name or group["track_type"] != track_type:
            issues.append(_invalid_record(index, ValueError("track identity drift")))
            continue
        points = group["points"]
        if isinstance(points, list) and len(points) < _MAX_TRACK_POINTS:
            points.append(_TrackPoint(observed_at, latitude, longitude))
        for key in ("WMO_AGENCY", "USA_AGENCY"):
            agency = _text(row.get(key))
            agencies = group["agencies"]
            if agency and isinstance(agencies, set):
                agencies.add(agency)
        atcf_id = _identifier(row.get("USA_ATCF_ID"))
        atcf_ids = group["atcf_ids"]
        if atcf_id and isinstance(atcf_ids, set):
            atcf_ids.add(atcf_id)

    tracks: list[_Track] = []
    for sid, group in grouped.items():
        points = group["points"]
        if not isinstance(points, list) or not points:
            continue
        unique_points = tuple(
            sorted(
                set(points),
                key=lambda item: (
                    item.observed_at,
                    item.latitude,
                    item.longitude,
                ),
            )
        )
        raw_agencies = group["agencies"]
        agencies = (
            tuple(sorted(str(item) for item in raw_agencies))
            if isinstance(raw_agencies, set)
            else ()
        )
        raw_atcf_ids = group["atcf_ids"]
        atcf_ids = (
            tuple(sorted(str(item) for item in raw_atcf_ids))
            if isinstance(raw_atcf_ids, set)
            else ()
        )
        tracks.append(
            _Track(
                sid=sid,
                name=str(group["name"]),
                track_type=str(group["track_type"]),
                points=unique_points,
                agencies=agencies,
                atcf_ids=atcf_ids,
            )
        )
    return tuple(sorted(tracks, key=lambda item: item.sid)), issues


def _name_tokens(value: str) -> frozenset[str]:
    return frozenset(
        _normalized_name(item)
        for item in re.findall(r"[A-Za-z][A-Za-z_-]*", value)
        if _normalized_name(item)
    )


def _normalized_name(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _identifier(value: object) -> str:
    text = _text(value)
    return text if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", text) else ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


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
        IbtracsTrackAdapter.provider_name,
        "NOAA IBTrACS: The selected GDACS cyclone has no source-backed point for "
        "track reconciliation.",
        reason_code="event_geometry_unavailable",
    )


def _invalid_schema() -> ProviderIssue:
    return ProviderIssue(
        IbtracsTrackAdapter.provider_name,
        "NOAA IBTrACS: The active-track CSV had no supported schema.",
        reason_code="invalid_schema",
    )


def _invalid_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        IbtracsTrackAdapter.provider_name,
        "NOAA IBTrACS: A malformed active-track row was skipped.",
        reason_code="invalid_record",
        detail=f"row[{index}]: {error}",
    )


def _row_limit() -> ProviderIssue:
    return ProviderIssue(
        IbtracsTrackAdapter.provider_name,
        "NOAA IBTrACS: The bounded active-track row limit was reached.",
        reason_code="result_limit_reached",
    )


def _identity_not_reconciled(*, ambiguous: bool) -> ProviderIssue:
    return ProviderIssue(
        IbtracsTrackAdapter.provider_name,
        (
            "NOAA IBTrACS: Multiple tracks met the conservative identity rules."
            if ambiguous
            else "NOAA IBTrACS: No active track matched the selected GDACS storm "
            "name, start time, and position."
        ),
        reason_code="identity_not_reconciled",
    )
