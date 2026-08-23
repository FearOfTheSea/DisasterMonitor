"""EMSC SeismicPortal FDSN earthquake event discovery adapter."""

import re
from datetime import datetime, timedelta
from math import isfinite
from urllib.parse import urlencode

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
    WorldwideSelectionIntent,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    BoundaryValidationQuality,
    Country,
    Disaster,
    DisasterEvent,
    EarthquakeEvent,
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

EMSC_QUERY_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"
_EMSC_CATALOG = "EMSC-RTS"
_EMSC_RIGHTS_ID = "emsc-fdsn-event-cc-by-4.0"
_MAX_OFFSHORE_ASSOCIATION_DISTANCE_KM = 100.0


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} is invalid")
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError(f"{label} is invalid")
    return parsed


def _place_mentions_country(place: str, country: Country) -> bool:
    terms = (country.canonical_name, country.alpha3_code, *country.aliases)
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", place, re.IGNORECASE)
        for term in terms
        if term
    )


def _base_params(
    *, starttime: datetime, endtime: datetime, limit: int, orderby: str
) -> dict[str, str | int | float]:
    return {
        "format": "json",
        "catalog": _EMSC_CATALOG,
        "starttime": starttime.isoformat(),
        "endtime": endtime.isoformat(),
        "minmagnitude": 4.5,
        "orderby": orderby,
        "limit": limit,
    }


def build_emsc_params(
    query: DisasterQuery, *, now: datetime
) -> dict[str, str | int | float]:
    """Build a bounded EMSC request from normalized country geography."""
    starttime = query.date_from or now - timedelta(days=query.time_window_days)
    endtime = query.date_to or now
    generic_query = not any(
        (
            query.discriminator("event_id"),
            query.date_from,
            query.date_to,
            query.prefecture,
            query.city,
            query.latitude is not None and query.longitude is not None,
            query.discriminator("magnitude") is not None,
        )
    )
    params = _base_params(
        starttime=starttime,
        endtime=endtime,
        limit=50,
        orderby="magnitude" if generic_query else "time",
    )
    area = query.country.geographic_area
    params.update(
        {
            "minlatitude": area.min_latitude,
            "maxlatitude": area.max_latitude,
            "minlongitude": area.min_longitude,
            "maxlongitude": area.max_longitude,
        }
    )
    if query.latitude is not None and query.longitude is not None:
        params.update(
            {
                "minlatitude": max(area.min_latitude, query.latitude - 2),
                "maxlatitude": min(area.max_latitude, query.latitude + 2),
                "minlongitude": max(area.min_longitude, query.longitude - 2),
                "maxlongitude": min(area.max_longitude, query.longitude + 2),
            }
        )
    query_magnitude = query.discriminator("magnitude")
    if query_magnitude is not None:
        params["minmagnitude"] = float(query_magnitude) - 0.1
    raw_event_id = query.discriminator("event_id")
    if isinstance(raw_event_id, str) and raw_event_id.lower().startswith("emsc:"):
        params["eventid"] = raw_event_id.partition(":")[2]
    return params


def build_worldwide_emsc_params(
    query: WorldwideDisasterQuery, *, now: datetime
) -> dict[str, str | int | float]:
    """Build a bounded worldwide EMSC request without synthetic geography."""
    return _base_params(
        starttime=now - timedelta(days=query.time_window_days),
        endtime=now,
        limit=query.limit,
        orderby=(
            "magnitude"
            if query.selection_intent is WorldwideSelectionIntent.STRONGEST
            else "time"
        ),
    )


class EmscEarthquakeAdapter:
    """Find global scientific earthquake observations from EMSC SeismicPortal."""

    provider_name = "EMSC SeismicPortal"
    source_id = "emsc-earthquakes"
    allowed_hosts = frozenset({"www.seismicportal.eu"})

    def __init__(
        self,
        *,
        geography: CountryCatalog,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._geography = geography
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._max_response_bytes = max_response_bytes

    def _parse_feature(
        self,
        raw_feature: object,
        *,
        now: datetime,
        index: int,
        snapshot_id: str | None,
        country_query: DisasterQuery | None = None,
    ) -> tuple[WorldwideDisasterEvent | DisasterEvent | None, ProviderIssue | None]:
        try:
            if not isinstance(raw_feature, dict):
                raise ValueError("feature is not an object")
            if _text(raw_feature.get("type")) != "Feature":
                raise ValueError("feature type is invalid")
            properties = raw_feature.get("properties")
            geometry = raw_feature.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                raise ValueError("properties or geometry is missing")
            if _text(geometry.get("type")) != "Point":
                raise ValueError("geometry is not a point")
            coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                raise ValueError("coordinates are invalid")
            event_id = _text(raw_feature.get("id")) or _text(properties.get("unid"))
            event_time = normalize_timestamp(properties.get("time"))
            updated_at = normalize_timestamp(properties.get("lastupdate"))
            location = _text(properties.get("flynn_region"))
            source_event_id = _text(properties.get("source_id"))
            source_catalog = _text(properties.get("source_catalog"))
            if not event_id or event_time is None or not location:
                raise ValueError("identifier, event time, or region is missing")
            if properties.get("lastupdate") is not None and updated_at is None:
                raise ValueError("last update time is invalid")
            longitude = _number(coordinates[0], "longitude")
            latitude = _number(coordinates[1], "latitude")
            depth_km = _number(properties.get("depth"), "depth")
            magnitude = _number(properties.get("mag"), "magnitude")
        except (TypeError, ValueError, OverflowError) as error:
            return None, _invalid_record(index, error)

        geography_status = EventGeographyStatus.WORLDWIDE
        if country_query is not None:
            geography_status = EventGeographyStatus.IN_COUNTRY
            if not self._geography.contains(country_query.country, latitude, longitude):
                distance_km = (
                    country_query.country.geographic_area.distance_to_boundary_km(
                        latitude, longitude
                    )
                )
                if (
                    distance_km is None
                    or distance_km > _MAX_OFFSHORE_ASSOCIATION_DISTANCE_KM
                    or not _place_mentions_country(location, country_query.country)
                ):
                    return None, ProviderIssue(
                        self.provider_name,
                        f"{self.provider_name}: An event outside "
                        f"{country_query.country.canonical_name} was excluded.",
                        reason_code="country_mismatch",
                        detail=f"feature[{index}] coordinate failed country validation",
                    )
                geography_status = EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE

        canonical_url = "https://www.seismicportal.eu/eventdetails.html?" + urlencode(
            {"unid": event_id}
        )
        source = SourceReference(
            source_id=self.source_id,
            publisher="Euro-Mediterranean Seismological Centre (EMSC)",
            title=location,
            canonical_url=canonical_url,
            published_at=event_time,
            updated_at=updated_at,
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
            snapshot_id=snapshot_id,
        )
        provider_ids = [f"emsc:{event_id}"]
        if source_catalog and source_event_id:
            provider_ids.append(f"emsc-catalog:{source_catalog}:{source_event_id}")
        measurements = (
            EventMeasurement(MeasurementKind.MAGNITUDE, magnitude, source=source),
            EventMeasurement(MeasurementKind.DEPTH, depth_km, "km", source=source),
        )
        if country_query is None:
            return (
                WorldwideDisasterEvent(
                    event_id=f"emsc:{event_id}",
                    disaster=Disaster.EARTHQUAKE,
                    location=location,
                    event_time=event_time,
                    source=source,
                    geometry=point_event_geometry(latitude, longitude, source),
                    measurements=measurements,
                    provider_ids=tuple(provider_ids),
                ),
                None,
            )
        return (
            EarthquakeEvent(
                event_id=f"emsc:{event_id}",
                disaster=Disaster.EARTHQUAKE,
                location=location,
                country=country_query.country,
                event_time=event_time,
                source=source,
                geometry=point_event_geometry(latitude, longitude, source),
                measurements=measurements,
                provider_ids=tuple(provider_ids),
                geography_status=geography_status,
            ),
            None,
        )

    async def _fetch(
        self,
        params: dict[str, str | int | float],
        *,
        now: datetime,
        country_query: DisasterQuery | None,
    ) -> ProviderBatch[WorldwideDisasterEvent | DisasterEvent]:
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={key: str(value) for key, value in params.items()},
            rights_id=_EMSC_RIGHTS_ID,
            retrieved_at=now,
        )
        try:
            payload = await get_json(
                self._client,
                EMSC_QUERY_URL,
                allowed_hosts=self.allowed_hosts,
                params=params,
                max_bytes=self._max_response_bytes,
                provider_name=self.provider_name,
                capture=capture,
                accepted_content_types=frozenset({""}),
            )
        except DisasterProviderResponseError as error:
            if error.failure.reason_code == "empty_result":
                return ProviderBatch(issues=(_empty_result(),))
            raise
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise DisasterProviderResponseError(
                "The EMSC response was not a GeoJSON FeatureCollection.",
                reason_code="invalid_schema",
            )
        raw_features = payload.get("features")
        if not isinstance(raw_features, list):
            raise DisasterProviderResponseError(
                "The EMSC GeoJSON response had no feature list.",
                reason_code="invalid_schema",
            )
        snapshot_id = (
            capture.snapshot.snapshot_id if capture and capture.snapshot else None
        )
        events: list[WorldwideDisasterEvent | DisasterEvent] = []
        issues: list[ProviderIssue] = []
        for index, raw_feature in enumerate(raw_features):
            event, issue = self._parse_feature(
                raw_feature,
                now=now,
                index=index,
                snapshot_id=snapshot_id,
                country_query=country_query,
            )
            if event is not None:
                events.append(event)
            if issue is not None:
                issues.append(issue)
        if not events and not issues:
            issues.append(_empty_result())
        if (
            country_query is not None
            and events
            and country_query.country.geographic_area.validation_quality
            is BoundaryValidationQuality.BOUNDING_BOX
        ):
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: Country membership was validated only "
                    "against an approximate bounding box.",
                    reason_code="country_membership_approximate",
                )
            )
        return ProviderBatch(tuple(events), tuple(issues))

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if (
            not isinstance(query, DisasterQuery)
            or query.disaster is not Disaster.EARTHQUAKE
        ):
            return ProviderBatch()
        result = await self._fetch(
            build_emsc_params(query, now=now), now=now, country_query=query
        )
        return ProviderBatch(
            tuple(item for item in result.records if isinstance(item, DisasterEvent)),
            result.issues,
        )

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[WorldwideDisasterEvent]:
        if (
            not isinstance(query, WorldwideDisasterQuery)
            or query.disaster is not Disaster.EARTHQUAKE
            or query.limit <= 0
        ):
            return ProviderBatch()
        result = await self._fetch(
            build_worldwide_emsc_params(query, now=now),
            now=now,
            country_query=None,
        )
        return ProviderBatch(
            tuple(
                item
                for item in result.records
                if isinstance(item, WorldwideDisasterEvent)
            ),
            result.issues,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _invalid_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        EmscEarthquakeAdapter.provider_name,
        f"{EmscEarthquakeAdapter.provider_name}: A malformed event record was skipped.",
        reason_code="invalid_record",
        detail=f"feature[{index}]: {error}",
    )


def _empty_result() -> ProviderIssue:
    return ProviderIssue(
        EmscEarthquakeAdapter.provider_name,
        f"{EmscEarthquakeAdapter.provider_name}: The provider returned no "
        "matching records.",
        reason_code="empty_result",
    )
