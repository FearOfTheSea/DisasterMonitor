"""NASA COOLR report-catalog landslide event discovery."""

import json
from collections.abc import Mapping
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
    EventGeographyStatus,
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

COOLR_QUERY_URL = (
    "https://gis.earthdata.nasa.gov/gis01/rest/services/Landslides/"
    "COOLR_Reports_Points/FeatureServer/0/query"
)
_COOLR_FEATURE_URL = (
    "https://gis.earthdata.nasa.gov/gis01/rest/services/Landslides/"
    "COOLR_Reports_Points/FeatureServer/0"
)
_COOLR_RIGHTS_ID = "nasa-coolr-report-catalog"
_MAX_TIME_WINDOW_DAYS = 30
_MAX_RECORDS = 50
_APPROVED_IMPORT_SOURCES = frozenset({"GLC", "LRC"})
_COORDINATE_TOLERANCE = 1e-4
_OUT_FIELDS = (
    "objectid",
    "event_id",
    "event_date",
    "event_time",
    "event_title",
    "location_description",
    "landslide_category",
    "landslide_trigger",
    "landslide_size",
    "event_import_source",
    "event_import_id",
    "latitude",
    "longitude",
    "country_name",
    "country_code",
    "admin_division_name",
    "source_name",
    "submitted_date",
    "last_edited_date",
)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is not an object")
    return value


def _strict_timestamp(value: object, label: str) -> datetime:
    if isinstance(value, bool):
        raise ValueError(f"{label} is invalid")
    if isinstance(value, (int, float)):
        milliseconds = float(value)
        if not isfinite(milliseconds):
            raise ValueError(f"{label} is invalid")
        try:
            return datetime.fromtimestamp(milliseconds / 1_000, tz=UTC)
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError(f"{label} is invalid") from error
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


def _coordinate(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} is invalid")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{label} is invalid")
    return number


def _point_from_fields(attributes: Mapping[str, object]) -> tuple[float, float] | None:
    latitude_value = attributes.get("latitude")
    longitude_value = attributes.get("longitude")
    if latitude_value is None and longitude_value is None:
        return None
    if latitude_value is None or longitude_value is None:
        raise ValueError("explicit latitude and longitude must be paired")
    latitude = _coordinate(latitude_value, "latitude")
    longitude = _coordinate(longitude_value, "longitude")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("explicit coordinates are outside WGS84")
    return latitude, longitude


def _point_from_geometry(raw_geometry: object) -> tuple[float, float] | None:
    if raw_geometry is None:
        return None
    geometry = _mapping(raw_geometry, "feature geometry")
    spatial_reference = geometry.get("spatialReference")
    if spatial_reference is not None:
        reference = _mapping(spatial_reference, "geometry spatial reference")
        wkid = reference.get("wkid", reference.get("latestWkid"))
        if wkid is not None and wkid != 4326:
            raise ValueError("feature geometry is not WGS84")
    if geometry.get("x") is None or geometry.get("y") is None:
        raise ValueError("feature point geometry is incomplete")
    longitude = _coordinate(geometry.get("x"), "feature longitude")
    latitude = _coordinate(geometry.get("y"), "feature latitude")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("feature geometry is outside WGS84")
    return latitude, longitude


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


def _date_predicate(start: datetime, end: datetime) -> str:
    return (
        f"event_date >= DATE '{start.date().isoformat()}' AND "
        f"event_date <= DATE '{end.date().isoformat()}'"
    )


def build_coolr_params(
    query: DisasterQuery | WorldwideDisasterQuery,
    *,
    now: datetime,
    country: Country | None,
) -> dict[str, str | int]:
    """Build the bounded standardized ArcGIS query for COOLR reports."""
    start, end = _time_window(query, now=now)
    limit = min(
        _MAX_RECORDS,
        max(1, query.limit)
        if isinstance(query, WorldwideDisasterQuery)
        else _MAX_RECORDS,
    )
    where = f"{_date_predicate(start, end)} AND event_import_source IN ('GLC', 'LRC')"
    params: dict[str, str | int] = {
        "f": "json",
        "where": where,
        "outFields": ",".join(_OUT_FIELDS),
        "returnGeometry": "true",
        "outSR": "4326",
        "orderByFields": "event_date DESC",
        "resultRecordCount": limit,
    }
    if country is not None:
        area = country.geographic_area
        params.update(
            {
                "geometry": json.dumps(
                    {
                        "xmin": area.min_longitude,
                        "ymin": area.min_latitude,
                        "xmax": area.max_longitude,
                        "ymax": area.max_latitude,
                        "spatialReference": {"wkid": 4326},
                    },
                    separators=(",", ":"),
                ),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
            }
        )
    return params


class NasaCoolrLandslideAdapter:
    """Discover observed COOLR landslide reports without elevating their provenance."""

    provider_name = "NASA COOLR Landslides"
    source_id = "nasa-coolr-landslides"
    allowed_hosts = frozenset({"gis.earthdata.nasa.gov"})

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

    def _parse_feature(
        self,
        raw_feature: object,
        *,
        now: datetime,
        start: datetime,
        end: datetime,
        index: int,
        country: Country | None,
        snapshot_id: str | None,
    ) -> tuple[WorldwideDisasterEvent | DisasterEvent | None, ProviderIssue | None]:
        try:
            feature = _mapping(raw_feature, "feature")
            attributes = _mapping(feature.get("attributes"), "feature attributes")
            import_source = _text(attributes.get("event_import_source")).upper()
            if import_source not in _APPROVED_IMPORT_SOURCES:
                return None, ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: A report with an unapproved import "
                    "source was skipped.",
                    reason_code="unsupported_import_source",
                    detail=f"feature[{index}] source={import_source or '<missing>'}",
                )
            event_time = _strict_timestamp(attributes.get("event_date"), "event_date")
            if not start <= event_time <= end:
                return None, None
            geometry_point = _point_from_geometry(feature.get("geometry"))
            fields_point = _point_from_fields(attributes)
            if geometry_point is None and fields_point is None:
                raise ValueError("no source-backed point coordinate is available")
            if geometry_point is not None and fields_point is not None:
                if (
                    abs(geometry_point[0] - fields_point[0]) > _COORDINATE_TOLERANCE
                    or _longitude_distance(geometry_point[1], fields_point[1])
                    > _COORDINATE_TOLERANCE
                ):
                    raise ValueError("feature and explicit coordinates disagree")
            point = geometry_point if geometry_point is not None else fields_point
            if point is None:
                raise ValueError("no source-backed point coordinate is available")
            latitude, longitude = point
            event_identifier = _identifier(attributes.get("event_id"))
            object_identifier = _identifier(attributes.get("objectid"))
            if not event_identifier and not object_identifier:
                raise ValueError("event_id and objectid are missing")
            location = _location(attributes)
            if not location:
                raise ValueError("location text is missing")
        except (TypeError, ValueError) as error:
            return None, _invalid_record(index, error)

        if country is not None:
            if self._geography is None:
                return None, _country_projection_unusable(index)
            projected_country = self._geography.get_by_alpha3(country.alpha3_code)
            if projected_country is None:
                return None, _country_projection_unusable(index)
            if not self._geography.contains(projected_country, latitude, longitude):
                return None, ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: An event outside "
                    f"{country.canonical_name} was excluded.",
                    reason_code="country_mismatch",
                    detail=f"feature[{index}] coordinate failed country validation",
                )

        event_id = (
            f"coolr:{event_identifier}"
            if event_identifier
            else f"coolr:objectid:{object_identifier}"
        )
        import_identifier = _text(attributes.get("event_import_id"))
        provider_ids = [event_id]
        if import_identifier:
            provider_ids.append(f"{import_source}:{import_identifier}")
        update_at = event_time
        for field_name in ("last_edited_date", "submitted_date"):
            raw_update = attributes.get(field_name)
            if raw_update is None or raw_update == "":
                continue
            try:
                update_at = _strict_timestamp(raw_update, field_name)
            except ValueError:
                continue
            break
        object_or_event_id = object_identifier or event_identifier
        canonical_url = f"{_COOLR_FEATURE_URL}/{quote(object_or_event_id, safe='')}"
        source = SourceReference(
            source_id=self.source_id,
            publisher="NASA Cooperative Open Online Landslide Repository (COOLR)",
            title=_text(attributes.get("event_title")) or location,
            canonical_url=canonical_url,
            published_at=event_time,
            updated_at=update_at,
            retrieved_at=now.astimezone(UTC),
            authority=SourceAuthority.SECONDARY,
            snapshot_id=snapshot_id,
        )
        geometry = point_event_geometry(latitude, longitude, source)
        size = _text(attributes.get("landslide_size"))
        measurements = (
            (EventMeasurement(MeasurementKind.SEVERITY, size, source=source),)
            if size
            else ()
        )
        if country is None:
            return (
                WorldwideDisasterEvent(
                    event_id=event_id,
                    disaster=Disaster.LANDSLIDE,
                    location=location,
                    event_time=event_time,
                    source=source,
                    geometry=geometry,
                    measurements=measurements,
                    provider_ids=tuple(provider_ids),
                ),
                None,
            )
        return (
            DisasterEvent(
                event_id=event_id,
                disaster=Disaster.LANDSLIDE,
                location=location,
                country=country,
                event_time=event_time,
                source=source,
                geometry=geometry,
                measurements=measurements,
                provider_ids=tuple(provider_ids),
                geography_status=EventGeographyStatus.IN_COUNTRY,
            ),
            None,
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
            params = build_coolr_params(query, now=now, country=country)
        except ValueError as error:
            return ProviderBatch(issues=(_invalid_query(error),))
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={key: str(value) for key, value in params.items()},
            rights_id=_COOLR_RIGHTS_ID,
            retrieved_at=now.astimezone(UTC),
        )
        payload = await get_json(
            self._client,
            COOLR_QUERY_URL,
            params=params,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        response = _mapping(payload, "COOLR response")
        if "error" in response:
            raise DisasterProviderResponseError(
                "The COOLR response contained an ArcGIS error.",
                reason_code="invalid_schema",
            )
        raw_features = response.get("features")
        if not isinstance(raw_features, list):
            raise DisasterProviderResponseError(
                "The COOLR response had no feature list.", reason_code="invalid_schema"
            )
        snapshot_id = (
            capture.snapshot.snapshot_id if capture and capture.snapshot else None
        )
        records: list[WorldwideDisasterEvent | DisasterEvent] = []
        issues: list[ProviderIssue] = []
        for index, raw_feature in enumerate(raw_features[:_MAX_RECORDS]):
            record, issue = self._parse_feature(
                raw_feature,
                now=now,
                start=start,
                end=end,
                index=index,
                country=country,
                snapshot_id=snapshot_id,
            )
            if record is not None:
                records.append(record)
            if issue is not None:
                issues.append(issue)
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
            or query.disaster is not Disaster.LANDSLIDE
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
            or query.disaster is not Disaster.LANDSLIDE
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


def _identifier(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    return _text(value)


def _longitude_distance(first: float, second: float) -> float:
    return min(abs(first - second), 360 - abs(first - second))


def _location(attributes: Mapping[str, object]) -> str:
    for field_name in (
        "location_description",
        "event_title",
        "admin_division_name",
        "country_name",
        "country_code",
    ):
        value = _text(attributes.get(field_name))
        if value:
            return value
    return ""


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
                NasaCoolrLandslideAdapter.provider_name,
                f"{NasaCoolrLandslideAdapter.provider_name}: Conflicting duplicate "
                "event identities were excluded.",
                reason_code="duplicate_identity",
                detail=f"normalized event {record.event_id!r} at feature {index}",
            )
        )
    return list(unique.values()), tuple(issues)


def _invalid_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        NasaCoolrLandslideAdapter.provider_name,
        f"{NasaCoolrLandslideAdapter.provider_name}: A malformed report was skipped.",
        reason_code="invalid_record",
        detail=f"feature[{index}]: {error}",
    )


def _country_projection_unusable(index: int) -> ProviderIssue:
    return ProviderIssue(
        NasaCoolrLandslideAdapter.provider_name,
        f"{NasaCoolrLandslideAdapter.provider_name}: A country report lacked "
        "usable country projection and was excluded.",
        reason_code="country_projection_unusable",
        detail=(
            "country catalog projection unavailable"
            if index < 0
            else f"feature[{index}] has no usable country projection"
        ),
    )


def _invalid_query(error: Exception) -> ProviderIssue:
    return ProviderIssue(
        NasaCoolrLandslideAdapter.provider_name,
        f"{NasaCoolrLandslideAdapter.provider_name}: The normalized query "
        "window is invalid.",
        reason_code="invalid_query",
        detail=str(error),
    )
