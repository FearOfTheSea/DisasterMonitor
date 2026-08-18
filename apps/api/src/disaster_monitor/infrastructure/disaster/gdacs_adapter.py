"""Country-neutral GDACS tropical-cyclone event discovery adapter."""

from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx

from disaster_monitor.application.disaster import (
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    EventGeometry,
    EventMeasurement,
    Hazard,
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
    validate_network_target,
)

GDACS_SEARCH_URL = "https://www.gdacs.org/gdacsapi/api/Events/geteventlist/SEARCH"
GDACS_EVENT_DATA_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
_GDACS_EVENT_TYPE = "TC"
_GDACS_MAX_PAGE_SIZE = 100


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identifier(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    return _text(value)


def build_gdacs_params(
    query: WorldwideDisasterQuery, *, now: datetime
) -> dict[str, str | int]:
    """Build the official bounded GDACS event-list query."""
    return {
        "eventlist": _GDACS_EVENT_TYPE,
        "fromDate": (now - timedelta(days=query.time_window_days)).isoformat(),
        "toDate": now.isoformat(),
        "pageSize": min(query.limit, _GDACS_MAX_PAGE_SIZE),
        "pageNumber": 1,
    }


class GdacsTropicalCycloneAdapter:
    """Find worldwide tropical-cyclone events from the official GDACS API."""

    provider_name = "GDACS tropical cyclones"
    source_id = "gdacs-tropical-cyclones"
    allowed_hosts = frozenset({"www.gdacs.org"})

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    def _parse_feature(
        self,
        raw_feature: object,
        *,
        now: datetime,
        index: int,
        snapshot_id: str | None,
    ) -> tuple[WorldwideDisasterEvent | None, tuple[ProviderIssue, ...]]:
        try:
            if not isinstance(raw_feature, dict):
                raise ValueError("feature is not an object")
            if _text(raw_feature.get("type")) != "Feature":
                raise ValueError("feature type is invalid")
            properties = raw_feature.get("properties")
            if not isinstance(properties, dict):
                raise ValueError("properties are missing")
            if _text(properties.get("eventtype")) != _GDACS_EVENT_TYPE:
                raise ValueError("event type is not tropical cyclone")
            raw_event_id = _identifier(properties.get("eventid"))
            event_time = normalize_timestamp(properties.get("todate")) or (
                normalize_timestamp(properties.get("fromdate"))
            )
            location = (
                _text(properties.get("country"))
                or _text(properties.get("name"))
                or _text(properties.get("eventname"))
                or _text(properties.get("description"))
            )
            if not raw_event_id or event_time is None or not location:
                raise ValueError("event identifier, time, or location is missing")
        except (TypeError, ValueError, OverflowError) as error:
            return None, (_invalid_record(index, error),)

        event_id = f"gdacs:tc:{raw_event_id}"
        episode_id = _identifier(properties.get("episodeid"))
        provider_ids = (
            (event_id, f"{event_id}:{episode_id}") if episode_id else (event_id,)
        )
        source = SourceReference(
            source_id=self.source_id,
            publisher="Global Disaster Alert and Coordination System (GDACS)",
            title=(
                _text(properties.get("name"))
                or _text(properties.get("description"))
                or "GDACS tropical cyclone event"
            ),
            canonical_url=self._event_url(properties, raw_event_id),
            published_at=None,
            updated_at=normalize_timestamp(properties.get("datemodified")),
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
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
        event = WorldwideDisasterEvent(
            event_id=event_id,
            hazard=Hazard.TROPICAL_CYCLONE,
            location=location,
            event_time=event_time,
            source=source,
            geometry=geometry,
            measurements=measurements,
            provider_ids=provider_ids,
        )
        return event, (geometry_issue,) if geometry_issue is not None else ()

    def _event_url(self, properties: dict[object, object], event_id: str) -> str:
        urls = properties.get("url")
        details = urls.get("details") if isinstance(urls, dict) else None
        try:
            validate_network_target(_text(details), self.allowed_hosts)
        except DisasterProviderResponseError:
            params = urlencode({"eventtype": _GDACS_EVENT_TYPE, "eventid": event_id})
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

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[WorldwideDisasterEvent]:
        if not isinstance(query, WorldwideDisasterQuery):
            return ProviderBatch()
        if query.hazard is not Hazard.TROPICAL_CYCLONE or query.limit <= 0:
            return ProviderBatch()

        params = build_gdacs_params(query, now=now)
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "eventtype": _GDACS_EVENT_TYPE,
                "from": str(params["fromDate"]),
                "to": str(params["toDate"]),
                "limit": str(query.limit),
            },
            rights_id="gdacs-api-terms-2025-03",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            GDACS_SEARCH_URL,
            allowed_hosts=self.allowed_hosts,
            params=params,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
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

        events: list[WorldwideDisasterEvent] = []
        issues: list[ProviderIssue] = []
        snapshot_id = (
            capture.snapshot.snapshot_id if capture and capture.snapshot else None
        )
        for index, raw_feature in enumerate(raw_features):
            event, feature_issues = self._parse_feature(
                raw_feature,
                now=now,
                index=index,
                snapshot_id=snapshot_id,
            )
            if event is not None:
                events.append(event)
            issues.extend(feature_issues)
        if not events and not issues:
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    f"{self.provider_name}: The provider returned no matching records.",
                    reason_code="empty_result",
                )
            )
        return ProviderBatch(records=tuple(events), issues=tuple(issues))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _invalid_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        GdacsTropicalCycloneAdapter.provider_name,
        "GDACS tropical cyclones: A malformed event record was skipped.",
        reason_code="invalid_record",
        detail=f"feature[{index}]: {error}",
    )
