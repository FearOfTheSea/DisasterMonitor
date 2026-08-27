"""Country-neutral GDACS event-discovery adapters."""

from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.ports.temporal_normalization import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    EventGeometry,
    EventMeasurement,
    MeasurementKind,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_json,
    validate_network_target,
)

GDACS_SEARCH_URL = "https://www.gdacs.org/gdacsapi/api/Events/geteventlist/SEARCH"
GDACS_EVENT_DATA_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
_GDACS_MAX_PAGE_SIZE = 100
_GDACS_MAX_PAGES = 5
_GDACS_MAX_RECORDS = _GDACS_MAX_PAGE_SIZE * _GDACS_MAX_PAGES
_GDACS_RIGHTS_ID = "gdacs-terms-of-use"


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identifier(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    return _text(value)


def _iso3_code(value: object) -> str:
    code = _text(value).upper()
    return code if len(code) == 3 and code.isascii() and code.isalpha() else ""


def _associated_country_codes(properties: dict[object, object]) -> frozenset[str]:
    """Return only GDACS structured ISO-3 country-association evidence."""
    codes: set[str] = set()
    primary_code = _iso3_code(properties.get("iso3"))
    if primary_code:
        codes.add(primary_code)
    affected_countries = properties.get("affectedcountries")
    if isinstance(affected_countries, list):
        for country in affected_countries:
            if not isinstance(country, dict):
                continue
            affected_code = _iso3_code(country.get("iso3"))
            if affected_code:
                codes.add(affected_code)
    return frozenset(codes)


def build_gdacs_params(
    query: WorldwideDisasterQuery | DisasterQuery,
    *,
    now: datetime,
    event_type: str = "TC",
    page_number: int = 1,
) -> dict[str, str | int]:
    """Build the official bounded GDACS event-list query."""
    start = (
        query.date_from
        if isinstance(query, DisasterQuery) and query.date_from is not None
        else now - timedelta(days=query.time_window_days)
    )
    end = (
        query.date_to
        if isinstance(query, DisasterQuery) and query.date_to is not None
        else now
    )
    return {
        "eventlist": event_type,
        "fromDate": start.isoformat(),
        "toDate": end.isoformat(),
        "pageSize": _GDACS_MAX_PAGE_SIZE,
        "pageNumber": page_number,
    }


class _GdacsEventAdapter:
    """Find one admitted GDACS event type from the official event-list API."""

    provider_name: str
    source_id: str
    disaster: Disaster
    event_type: str
    allowed_hosts = frozenset({"www.gdacs.org"})

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
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    def _parse_feature(
        self,
        raw_feature: object,
        *,
        now: datetime,
        index: int,
        snapshot_id: str | None,
        country_query: DisasterQuery | None = None,
    ) -> tuple[
        WorldwideDisasterEvent | DisasterEvent | None, tuple[ProviderIssue, ...]
    ]:
        try:
            if not isinstance(raw_feature, dict):
                raise ValueError("feature is not an object")
            if _text(raw_feature.get("type")) != "Feature":
                raise ValueError("feature type is invalid")
            properties = raw_feature.get("properties")
            if not isinstance(properties, dict):
                raise ValueError("properties are missing")
            if _text(properties.get("eventtype")) != self.event_type:
                raise ValueError(f"event type is not {self.event_type}")
            if country_query is not None and country_query.country.alpha3_code not in (
                _associated_country_codes(properties)
            ):
                return None, ()
            raw_event_id = _identifier(properties.get("eventid"))
            event_time = normalize_timestamp(properties.get("fromdate"))
            end_time = normalize_timestamp(properties.get("todate"))
            location = (
                _text(properties.get("country"))
                or _text(properties.get("name"))
                or _text(properties.get("eventname"))
                or _text(properties.get("description"))
            )
            if not raw_event_id or event_time is None or not location:
                raise ValueError("event identifier, time, or location is missing")
            if properties.get("todate") is not None and end_time is None:
                raise ValueError("event end time is invalid")
            if end_time is not None and end_time < event_time:
                raise ValueError("event interval ends before it starts")
        except (TypeError, ValueError, OverflowError) as error:
            return None, (_invalid_record(self.provider_name, index, error),)

        event_id = f"gdacs:{self.event_type.lower()}:{raw_event_id}"
        episode_id = _identifier(properties.get("episodeid"))
        provider_ids = [event_id]
        if episode_id:
            provider_ids.append(f"{event_id}:{episode_id}")
        glide_id = _text(properties.get("glide"))
        if glide_id:
            provider_ids.append(f"glide:{glide_id}")
        upstream_name = _text(properties.get("source"))
        upstream_id = _identifier(properties.get("sourceid"))
        if upstream_name and upstream_id:
            provider_ids.append(f"gdacs-source:{upstream_name}:{upstream_id}")
        publisher = "Global Disaster Alert and Coordination System (GDACS)"
        if upstream_name:
            publisher = f"{publisher}; source: {upstream_name}"
        source = SourceReference(
            source_id=self.source_id,
            publisher=publisher,
            title=(
                _text(properties.get("name"))
                or _text(properties.get("description"))
                or f"GDACS {self.disaster.value.replace('_', ' ')} event"
            ),
            canonical_url=self._event_url(properties, raw_event_id),
            published_at=None,
            updated_at=normalize_timestamp(properties.get("datemodified")),
            retrieved_at=now,
            authority=SourceAuthority.SECONDARY,
            snapshot_id=snapshot_id,
        )
        geometry, geometry_issue = self._point_geometry(
            raw_feature.get("geometry"), source, index=index
        )
        severity = _text(properties.get("alertlevel"))
        measurements = (
            (EventMeasurement(MeasurementKind.SEVERITY, severity, source=source),)
            if severity
            else ()
        )
        if country_query is None:
            event: WorldwideDisasterEvent | DisasterEvent = WorldwideDisasterEvent(
                event_id=event_id,
                disaster=self.disaster,
                location=location,
                event_time=event_time,
                source=source,
                geometry=geometry,
                measurements=measurements,
                provider_ids=tuple(provider_ids),
            )
        else:
            projected_country = (
                self._geography.get_by_alpha3(country_query.country.alpha3_code)
                if self._geography is not None
                else None
            )
            if (
                projected_country is None
                or geometry is None
                or len(geometry.coordinates) != 1
            ):
                return None, (
                    geometry_issue,
                    _country_projection_unusable(self.provider_name, index),
                ) if geometry_issue is not None else (
                    _country_projection_unusable(self.provider_name, index),
                )
            point = geometry.coordinates[0]
            try:
                geography_status = (
                    EventGeographyStatus.IN_COUNTRY
                    if self._geography is not None
                    and self._geography.contains(
                        projected_country, point.latitude, point.longitude
                    )
                    else EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
                )
            except (AttributeError, TypeError, ValueError):
                return None, (_country_projection_unusable(self.provider_name, index),)
            event = DisasterEvent(
                event_id=event_id,
                disaster=self.disaster,
                location=location,
                country=country_query.country,
                event_time=event_time,
                source=source,
                geometry=geometry,
                measurements=measurements,
                provider_ids=tuple(provider_ids),
                geography_status=geography_status,
            )
        return event, (geometry_issue,) if geometry_issue is not None else ()

    def _event_url(self, properties: dict[object, object], event_id: str) -> str:
        urls = properties.get("url")
        details = urls.get("details") if isinstance(urls, dict) else None
        try:
            validate_network_target(_text(details), self.allowed_hosts)
        except DisasterProviderResponseError:
            params = urlencode({"eventtype": self.event_type, "eventid": event_id})
            return f"{GDACS_EVENT_DATA_URL}?{params}"
        return _text(details)

    def _point_geometry(
        self,
        raw_geometry: object,
        source: SourceReference,
        *,
        index: int,
    ) -> tuple[EventGeometry | None, ProviderIssue | None]:
        if raw_geometry is None:
            return None, None
        try:
            if not isinstance(raw_geometry, dict):
                raise ValueError("geometry is not an object")
            if _text(raw_geometry.get("type")) != "Point":
                raise ValueError("geometry is not a supported point")
            coordinates = raw_geometry.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                raise ValueError("point coordinates are missing")
            longitude, latitude = coordinates[:2]
            if isinstance(longitude, bool) or isinstance(latitude, bool):
                raise ValueError("point coordinates are invalid")
            return point_event_geometry(float(latitude), float(longitude), source), None
        except (TypeError, ValueError, OverflowError) as error:
            return None, ProviderIssue(
                self.provider_name,
                f"{self.provider_name}: Source geometry for one event was omitted.",
                reason_code="invalid_geometry",
                detail=f"feature[{index}]: {error}",
            )

    async def _fetch_events(
        self,
        query: WorldwideDisasterQuery | DisasterQuery,
        *,
        now: datetime,
        country_query: DisasterQuery | None = None,
    ) -> ProviderBatch[WorldwideDisasterEvent | DisasterEvent]:
        events: list[WorldwideDisasterEvent | DisasterEvent] = []
        issues: list[ProviderIssue] = []
        seen_event_ids: set[str] = set()
        raw_record_count = 0
        saw_raw_features = False
        for page_number in range(1, _GDACS_MAX_PAGES + 1):
            params = build_gdacs_params(
                query,
                now=now,
                event_type=self.event_type,
                page_number=page_number,
            )
            capture = build_snapshot_capture(
                self._snapshot_recorder,
                source_id=self.source_id,
                parameters={
                    "eventtype": self.event_type,
                    "from": str(params["fromDate"]),
                    "to": str(params["toDate"]),
                    "page": str(page_number),
                    "page_size": str(_GDACS_MAX_PAGE_SIZE),
                },
                rights_id=_GDACS_RIGHTS_ID,
                retrieved_at=now,
            )
            try:
                payload = await get_json(
                    self._client,
                    GDACS_SEARCH_URL,
                    allowed_hosts=self.allowed_hosts,
                    params=params,
                    max_bytes=self._max_response_bytes,
                    provider_name=self.provider_name,
                    capture=capture,
                    accepted_content_types=frozenset({""}),
                )
                raw_features = _feature_list(payload)
            except DisasterProviderError as error:
                if page_number == 1:
                    if error.failure.reason_code == "empty_result":
                        return ProviderBatch(
                            issues=(_empty_result(self.provider_name),)
                        )
                    raise
                issues.append(
                    _pagination_failure(self.provider_name, page_number, error)
                )
                break

            saw_raw_features = saw_raw_features or bool(raw_features)
            snapshot_id = (
                capture.snapshot.snapshot_id if capture and capture.snapshot else None
            )
            remaining_records = _GDACS_MAX_RECORDS - raw_record_count
            for index, raw_feature in enumerate(raw_features[:remaining_records]):
                event, feature_issues = self._parse_feature(
                    raw_feature,
                    now=now,
                    index=raw_record_count + index,
                    snapshot_id=snapshot_id,
                    country_query=country_query,
                )
                if event is not None and event.event_id not in seen_event_ids:
                    events.append(event)
                    seen_event_ids.add(event.event_id)
                issues.extend(feature_issues)
            raw_record_count += min(len(raw_features), remaining_records)
            if len(raw_features) < _GDACS_MAX_PAGE_SIZE:
                break
            if raw_record_count >= _GDACS_MAX_RECORDS:
                issues.append(_pagination_limit(self.provider_name))
                break

        if (
            not events
            and not issues
            and (country_query is None or not saw_raw_features)
        ):
            issues.append(_empty_result(self.provider_name))
        return ProviderBatch(records=tuple(events), issues=tuple(issues))

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[WorldwideDisasterEvent]:
        if not isinstance(query, WorldwideDisasterQuery):
            return ProviderBatch()
        if query.disaster is not self.disaster or query.limit <= 0:
            return ProviderBatch()
        result = await self._fetch_events(query, now=now)
        return ProviderBatch(
            records=tuple(
                event
                for event in result.records
                if isinstance(event, WorldwideDisasterEvent)
            ),
            issues=result.issues,
        )

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if not isinstance(query, DisasterQuery):
            return ProviderBatch()
        if query.disaster is not self.disaster:
            return ProviderBatch()
        if (
            self._geography is None
            or self._geography.get_by_alpha3(query.country.alpha3_code) is None
        ):
            return ProviderBatch(
                issues=(_country_projection_unusable(self.provider_name, -1),)
            )
        result = await self._fetch_events(query, now=now, country_query=query)
        return ProviderBatch(
            records=tuple(
                event for event in result.records if isinstance(event, DisasterEvent)
            ),
            issues=result.issues,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class GdacsTropicalCycloneAdapter(_GdacsEventAdapter):
    """Discover GDACS tropical-cyclone events."""

    provider_name = "GDACS tropical cyclones"
    source_id = "gdacs-tropical-cyclones"
    disaster = Disaster.TROPICAL_CYCLONE
    event_type = "TC"


class GdacsFloodAdapter(_GdacsEventAdapter):
    """Discover GDACS flood events without promoting impact estimates."""

    provider_name = "GDACS floods"
    source_id = "gdacs-floods"
    disaster = Disaster.FLOOD
    event_type = "FL"


class GdacsWildfireAdapter(_GdacsEventAdapter):
    """Discover GDACS wildfire events derived from GWIS curation."""

    provider_name = "GDACS wildfires"
    source_id = "gdacs-wildfires"
    disaster = Disaster.WILDFIRE
    event_type = "WF"


class GdacsVolcanicEruptionAdapter(_GdacsEventAdapter):
    """Discover GDACS volcanic-eruption events derived from VAA/GVP inputs."""

    provider_name = "GDACS volcanic eruptions"
    source_id = "gdacs-volcanic-eruptions"
    disaster = Disaster.VOLCANIC_ERUPTION
    event_type = "VO"


def _invalid_record(provider_name: str, index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        provider_name,
        f"{provider_name}: A malformed event record was skipped.",
        reason_code="invalid_record",
        detail=f"feature[{index}]: {error}",
    )


def _feature_list(payload: object) -> list[object]:
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise DisasterProviderResponseError(
            "The GDACS response was not a GeoJSON FeatureCollection.",
            reason_code="invalid_schema",
        )
    raw_features = payload.get("features")
    if not isinstance(raw_features, list):
        raise DisasterProviderResponseError(
            "The GDACS response had no feature list.",
            reason_code="invalid_schema",
        )
    return raw_features


def _pagination_failure(
    provider_name: str, page_number: int, error: DisasterProviderError
) -> ProviderIssue:
    failure = error.failure
    return ProviderIssue(
        provider_name,
        f"{provider_name}: Retrieval stopped after a later GDACS page failed; "
        "earlier records were retained.",
        reason_code=failure.reason_code,
        retryable=failure.retryable,
        http_status=failure.http_status,
        detail=f"page[{page_number}]: {failure.detail or str(error)}",
    )


def _pagination_limit(provider_name: str) -> ProviderIssue:
    return ProviderIssue(
        provider_name,
        f"{provider_name}: The bounded GDACS pagination ceiling was reached; "
        "coverage may be incomplete.",
        reason_code="pagination_limit_reached",
        detail=f"pages={_GDACS_MAX_PAGES}; records={_GDACS_MAX_RECORDS}",
    )


def _country_projection_unusable(provider_name: str, index: int) -> ProviderIssue:
    return ProviderIssue(
        provider_name,
        f"{provider_name}: A country-associated event lacked usable "
        "country projection and was excluded.",
        reason_code="country_projection_unusable",
        detail=(
            "country catalog projection unavailable"
            if index < 0
            else f"feature[{index}] has no usable country projection"
        ),
    )


def _empty_result(provider_name: str) -> ProviderIssue:
    return ProviderIssue(
        provider_name,
        f"{provider_name}: The provider returned no matching records.",
        reason_code="empty_result",
    )
