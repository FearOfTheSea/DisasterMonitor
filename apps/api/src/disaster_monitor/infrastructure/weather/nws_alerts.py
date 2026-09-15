"""Bounded NOAA/NWS GeoJSON adapter projected into generic CAP 1.2 records."""

import math
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlsplit

import httpx

from disaster_monitor.application.ports.temporal_normalization import (
    normalize_timestamp,
)
from disaster_monitor.application.ports.weather_alerts import (
    WeatherAlertBatch,
    WeatherAlertProviderIssue,
)
from disaster_monitor.application.weather_alerts import NWS_LIMITATIONS, NWS_SOURCE_ID
from disaster_monitor.domain.imagery.regions import MultiPolygon, polygon_from_geojson
from disaster_monitor.domain.warnings import (
    CapAlert,
    CapArea,
    CapInfo,
    CapMessageReference,
    CapMessageType,
    CapScope,
    CapStatus,
    WarningCertainty,
    WarningSeverity,
    WarningUrgency,
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
    "message_type": "alert,update,cancel",
    "region_type": "land",
}
_MAX_RING_COUNT = 20
_MAX_RING_COORDINATES = 2_000


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    value_text = _text(value)
    return value_text or None


def _enum[EnumValue: StrEnum](enum_type: type[EnumValue], value: object) -> EnumValue:
    try:
        return enum_type(_text(value).casefold())
    except ValueError:
        return enum_type("unknown")


def _required_enum[EnumValue: StrEnum](
    enum_type: type[EnumValue], value: object
) -> EnumValue:
    try:
        return enum_type(_text(value).casefold())
    except ValueError as error:
        raise ValueError(f"Unsupported CAP value {_text(value)!r}.") from error


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


def _polygon_geometry(raw: object) -> MultiPolygon | None:
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
    total_coordinates = 0
    for raw_ring in raw_rings:
        if not isinstance(raw_ring, list) or len(raw_ring) < 4:
            raise ValueError("An alert polygon ring is invalid.")
        total_coordinates += len(raw_ring)
        if total_coordinates > _MAX_RING_COORDINATES:
            raise ValueError("The alert polygon exceeds the coordinate limit.")
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
        if raw_ring[0][:2] != raw_ring[-1][:2]:
            raise ValueError("An alert polygon ring is not closed.")
    return polygon_from_geojson(raw)


def _pairs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        (str(key), str(item))
        for key, raw in sorted(value.items())
        for item in (raw if isinstance(raw, list) else [raw])
        if str(key).strip() and str(item).strip()
    )


def _references(value: object) -> tuple[CapMessageReference, ...]:
    if not isinstance(value, list):
        return ()
    result: list[CapMessageReference] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("An NWS CAP reference is malformed.")
        sent = normalize_timestamp(raw.get("sent"))
        sender = _text(raw.get("sender"))
        identifier = _text(raw.get("identifier"))
        if sent is None or not sender or not identifier:
            raise ValueError("An NWS CAP reference is malformed.")
        result.append(CapMessageReference(sender, identifier, sent))
    return tuple(result)


def _parse_alert(raw: object, *, now: datetime) -> CapAlert | None:
    if not isinstance(raw, dict):
        raise ValueError("An alert feature is not an object.")
    properties = raw.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("An alert feature has no properties object.")
    if _text(properties.get("status")) != "Actual":
        return None
    message_type = _required_enum(CapMessageType, properties.get("messageType"))
    if message_type not in {
        CapMessageType.ALERT,
        CapMessageType.UPDATE,
        CapMessageType.CANCEL,
    }:
        return None
    if _text(properties.get("category")) != "Met":
        return None
    identifier = _text(properties.get("id"))
    event = _text(properties.get("event"))
    publisher = _text(properties.get("senderName"))
    affected_area = _text(properties.get("areaDesc"))
    sent = normalize_timestamp(properties.get("sent"))
    expires = normalize_timestamp(properties.get("expires"))
    if (
        not identifier
        or not event
        or not publisher
        or not affected_area
        or sent is None
    ):
        raise ValueError(
            "An alert is missing required source identity or label fields."
        )
    effective = normalize_timestamp(properties.get("effective"))
    onset = normalize_timestamp(properties.get("onset"))
    for raw_value, parsed in (
        (properties.get("effective"), effective),
        (properties.get("onset"), onset),
        (properties.get("expires"), expires),
    ):
        if raw_value is not None and parsed is None:
            raise ValueError("An alert timestamp is malformed.")
    geometry = _polygon_geometry(raw.get("geometry"))
    info = CapInfo(
        language=_text(properties.get("language")) or "en-US",
        categories=("Met",),
        event=event,
        event_codes=_pairs(properties.get("eventCode")),
        urgency=_enum(WarningUrgency, properties.get("urgency")),
        severity=_enum(WarningSeverity, properties.get("severity")),
        certainty=_enum(WarningCertainty, properties.get("certainty")),
        effective=effective,
        onset=onset,
        expires=expires,
        sender_name=publisher,
        headline=_optional_text(properties.get("headline")),
        description=_optional_text(properties.get("description")),
        instruction=_optional_text(properties.get("instruction")),
        areas=(
            CapArea(
                affected_area,
                polygons=(geometry,) if geometry is not None else (),
                geocodes=_pairs(properties.get("geocode")),
            ),
        ),
        parameters=_pairs(properties.get("parameters")),
    )
    return CapAlert(
        identifier=identifier,
        sender=_text(properties.get("sender")) or "nws-alerts@noaa.gov",
        sent=sent,
        status=CapStatus.ACTUAL,
        message_type=message_type,
        scope=_required_enum(CapScope, properties.get("scope") or "Public"),
        source_id=NWS_SOURCE_ID,
        publisher=publisher,
        infos=(info,),
        references=_references(properties.get("references")),
        incidents=tuple(
            item for item in _text(properties.get("incidents")).split() if item
        ),
        canonical_url=_canonical_alert_url(raw.get("id")),
        source=_optional_text(properties.get("source")),
        retrieved_at=now,
        attribution=NWS_ATTRIBUTION,
        limitations=NWS_LIMITATIONS,
        profile="CAP-1.2/NWS",
    )


class NwsWeatherAlertsAdapter:
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
                        "DisasterMonitor/0.1 (local warning reader; "
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
        alerts: list[CapAlert] = []
        for raw in features[: self._maximum_records]:
            try:
                parsed = _parse_alert(raw, now=now)
            except (TypeError, ValueError):
                malformed += 1
                continue
            if parsed is not None:
                alerts.append(parsed)
        alerts.sort(key=lambda item: (item.sent, item.identifier), reverse=True)
        issue: WeatherAlertProviderIssue | None = None
        if reached_limit:
            issue = WeatherAlertProviderIssue(
                "record_limit_reached",
                f"The alert response exceeded the {self._maximum_records}-record "
                "ceiling.",
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
