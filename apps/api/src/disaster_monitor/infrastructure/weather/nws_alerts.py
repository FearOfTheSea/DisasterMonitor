"""Bounded NOAA/NWS active CAP alert adapter."""

import math
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from disaster_monitor.application.ports.temporal_normalization import (
    normalize_timestamp,
)
from disaster_monitor.application.ports.weather_alerts import (
    WeatherAlertBatch,
    WeatherAlertProviderIssue,
)
from disaster_monitor.application.weather_alerts import (
    NWS_LIMITATIONS,
    NWS_SOURCE_ID,
    WeatherAlert,
    WeatherAlertCertainty,
    WeatherAlertCoordinate,
    WeatherAlertGeometry,
    WeatherAlertSeverity,
    WeatherAlertUrgency,
)
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError
from disaster_monitor.infrastructure.disaster.http import (
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_json,
)

NWS_ACTIVE_ALERTS_URL = "https://api.weather.gov/alerts/active"
NWS_ATTRIBUTION = "NOAA/National Weather Service"
NWS_RIGHTS_ID = "noaa-nws-public-domain"
NWS_ACTIVE_PARAMETERS = {
    "status": "actual",
    "message_type": "alert,update",
    "region_type": "land",
}
_MAX_RING_COUNT = 20
_MAX_RING_COORDINATES = 2_000


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None


def _enum_value[
    WeatherAlertEnum: (
        WeatherAlertSeverity,
        WeatherAlertUrgency,
        WeatherAlertCertainty,
    )
](enum_type: type[WeatherAlertEnum], value: object) -> WeatherAlertEnum:
    text = _text(value).casefold()
    try:
        return enum_type(text)
    except ValueError:
        return enum_type("unknown")


def _canonical_alert_url(value: object) -> str | None:
    text = _text(value)
    try:
        target = urlsplit(text)
    except ValueError:
        return None
    if (
        target.scheme == "https"
        and (target.hostname or "").casefold() == "api.weather.gov"
        and target.path.startswith("/alerts/")
        and target.username is None
        and target.password is None
        and target.port in {None, 443}
    ):
        return text
    return None


def _polygon_geometry(raw: object) -> WeatherAlertGeometry | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("type") != "Polygon":
        raise ValueError("Only source-supplied GeoJSON Polygon geometry is admitted.")
    raw_rings = raw.get("coordinates")
    if (
        not isinstance(raw_rings, list)
        or not raw_rings
        or len(raw_rings) > _MAX_RING_COUNT
    ):
        raise ValueError("The alert polygon rings are invalid or exceed the limit.")
    rings: list[tuple[WeatherAlertCoordinate, ...]] = []
    total_coordinates = 0
    for raw_ring in raw_rings:
        if not isinstance(raw_ring, list) or len(raw_ring) < 4:
            raise ValueError("An alert polygon ring is invalid.")
        total_coordinates += len(raw_ring)
        if total_coordinates > _MAX_RING_COORDINATES:
            raise ValueError("The alert polygon exceeds the coordinate limit.")
        ring: list[WeatherAlertCoordinate] = []
        raw_pairs: list[tuple[float, float]] = []
        for raw_coordinate in raw_ring:
            if (
                not isinstance(raw_coordinate, list)
                or len(raw_coordinate) < 2
                or isinstance(raw_coordinate[0], bool)
                or isinstance(raw_coordinate[1], bool)
                or not isinstance(raw_coordinate[0], (int, float))
                or not isinstance(raw_coordinate[1], (int, float))
            ):
                raise ValueError("An alert polygon coordinate is invalid.")
            longitude = float(raw_coordinate[0])
            latitude = float(raw_coordinate[1])
            if (
                not math.isfinite(longitude)
                or not math.isfinite(latitude)
                or not -180 <= longitude <= 180
                or not -90 <= latitude <= 90
            ):
                raise ValueError("An alert polygon coordinate is outside WGS84.")
            raw_pairs.append((longitude, latitude))
            ring.append(WeatherAlertCoordinate(latitude, longitude))
        if raw_pairs[0] != raw_pairs[-1]:
            raise ValueError("An alert polygon ring is not closed.")
        rings.append(tuple(ring))
    return WeatherAlertGeometry(tuple(rings))


def _parse_alert(raw: object, *, now: datetime) -> WeatherAlert | None:
    if not isinstance(raw, dict):
        raise ValueError("An alert feature is not an object.")
    properties = raw.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("An alert feature has no properties object.")
    if _text(properties.get("status")) != "Actual":
        return None
    if _text(properties.get("messageType")) not in {"Alert", "Update"}:
        return None
    if _text(properties.get("category")) != "Met":
        return None
    provider_alert_id = _text(properties.get("id"))
    event = _text(properties.get("event"))
    publisher = _text(properties.get("senderName"))
    affected_area = _text(properties.get("areaDesc"))
    expires = normalize_timestamp(properties.get("expires"))
    if not provider_alert_id or not event or not publisher or not affected_area:
        raise ValueError(
            "An alert is missing required source identity or label fields."
        )
    if expires is not None and expires <= now:
        return None
    sent = normalize_timestamp(properties.get("sent"))
    effective = normalize_timestamp(properties.get("effective"))
    onset = normalize_timestamp(properties.get("onset"))
    for raw_value, parsed in (
        (properties.get("sent"), sent),
        (properties.get("effective"), effective),
        (properties.get("onset"), onset),
        (properties.get("expires"), expires),
    ):
        if raw_value is not None and parsed is None:
            raise ValueError("An alert timestamp is malformed.")
    return WeatherAlert(
        provider_alert_id=provider_alert_id,
        source_id=NWS_SOURCE_ID,
        publisher=publisher,
        event=event,
        headline=_optional_text(properties.get("headline")),
        severity=_enum_value(WeatherAlertSeverity, properties.get("severity")),
        urgency=_enum_value(WeatherAlertUrgency, properties.get("urgency")),
        certainty=_enum_value(WeatherAlertCertainty, properties.get("certainty")),
        sent=sent,
        effective=effective,
        onset=onset,
        expires=expires,
        affected_area=affected_area,
        geometry=_polygon_geometry(raw.get("geometry")),
        canonical_url=_canonical_alert_url(raw.get("id")),
        retrieved_at=now,
        attribution=NWS_ATTRIBUTION,
        limitations=NWS_LIMITATIONS,
    )


class NwsWeatherAlertsAdapter:
    """Retrieve active NWS meteorological alerts without event inference."""

    source_id = NWS_SOURCE_ID
    allowed_hosts = frozenset({"api.weather.gov"})

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        maximum_response_bytes: int = 3_000_000,
        maximum_records: int = 500,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._maximum_response_bytes = maximum_response_bytes
        self._maximum_records = maximum_records

    async def fetch_active_alerts(self, *, now: datetime) -> WeatherAlertBatch:
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters=NWS_ACTIVE_PARAMETERS,
            rights_id=NWS_RIGHTS_ID,
            retrieved_at=now,
        )
        try:
            payload = await get_json(
                self._client,
                NWS_ACTIVE_ALERTS_URL,
                params=NWS_ACTIVE_PARAMETERS,
                headers={
                    "Accept": "application/geo+json",
                    "User-Agent": (
                        "DisasterMonitor/0.1 "
                        "(local operational-awareness client; "
                        "no public warning delivery)"
                    ),
                },
                capture=capture,
                allowed_hosts=self.allowed_hosts,
                max_bytes=self._maximum_response_bytes,
                provider_name="NOAA/NWS alerts",
                accepted_content_types=frozenset({"application/geo+json"}),
            )
        except DisasterProviderError as error:
            return WeatherAlertBatch(
                issue=WeatherAlertProviderIssue(
                    error.failure.reason_code,
                    "The NOAA/NWS alert source request failed.",
                    retryable=error.failure.retryable,
                )
            )
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            return WeatherAlertBatch(
                issue=WeatherAlertProviderIssue(
                    "invalid_payload",
                    "The NOAA/NWS alert response was not a GeoJSON FeatureCollection.",
                )
            )
        features = payload.get("features")
        if not isinstance(features, list):
            return WeatherAlertBatch(
                issue=WeatherAlertProviderIssue(
                    "invalid_payload",
                    "The NOAA/NWS alert response did not contain a feature list.",
                )
            )
        reached_limit = len(features) > self._maximum_records
        malformed = 0
        alerts: list[WeatherAlert] = []
        for raw in features[: self._maximum_records]:
            try:
                parsed = _parse_alert(raw, now=now)
            except (TypeError, ValueError):
                malformed += 1
                continue
            if parsed is not None:
                alerts.append(parsed)
        alerts.sort(
            key=lambda item: (
                item.sent or item.effective or now,
                item.provider_alert_id,
            ),
            reverse=True,
        )
        issue: WeatherAlertProviderIssue | None = None
        if reached_limit:
            issue = WeatherAlertProviderIssue(
                "record_limit_reached",
                "The alert response exceeded the "
                f"{self._maximum_records}-record ceiling.",
                partial=True,
            )
        elif malformed:
            issue = WeatherAlertProviderIssue(
                "malformed_records",
                f"{malformed} malformed alert record(s) were excluded.",
                partial=True,
            )
        return WeatherAlertBatch(tuple(alerts), issue)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
