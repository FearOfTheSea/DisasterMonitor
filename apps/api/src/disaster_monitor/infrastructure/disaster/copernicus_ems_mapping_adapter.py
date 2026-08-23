"""Event-associated Copernicus EMS Rapid Mapping evidence for landslides."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

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
    sanitize_provider_text,
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
    get_json,
)

_ACTIVATION_INFO_URL = (
    "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/"
    "public-activations-info/"
)
_ACTIVATION_DETAIL_URL = (
    "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/"
    "public-activations/"
)
_CANONICAL_ROOT = "https://mapping.emergency.copernicus.eu/activations"
_MAX_TIME_DIFFERENCE = timedelta(days=3)
_MAX_DISTANCE_KM = 100.0
_MAX_CANDIDATES = 5
_CRISIS_PRODUCT_TYPES = frozenset({"DEL", "GRA"})
_POINT = re.compile(
    r"^\s*POINT\s*\(\s*"
    r"(?P<longitude>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+"
    r"(?P<latitude>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\)\s*$",
    re.IGNORECASE,
)
_RAPID_CODE = re.compile(r"^EMSR\d+$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Activation:
    code: str
    name: str
    countries: tuple[str, ...]
    event_time: datetime
    activation_time: datetime | None
    updated_at: datetime | None
    latitude: float
    longitude: float
    distance_km: float


class CopernicusRapidMappingAdapter:
    """Attach delivered crisis maps to a selected landslide event."""

    provider_name = "Copernicus EMS Rapid Mapping landslides"
    source_id = "copernicus-rapid-mapping-landslides"
    allowed_hosts = frozenset({"rapidmapping.emergency.copernicus.eu"})

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
        if (
            query.disaster is not Disaster.LANDSLIDE
            or event.disaster is not Disaster.LANDSLIDE
        ):
            return ProviderBatch()
        if event.country.alpha3_code != query.country.alpha3_code:
            return ProviderBatch()
        country_names = (
            query.country.canonical_name,
            *query.country.aliases,
        )
        return await self._get_reports(
            event,
            now=now,
            required_country_names=country_names,
            report_countries=(query.country.canonical_name,),
            country_codes=(query.country.alpha3_code,),
        )

    async def get_worldwide_situation_reports(
        self,
        event: WorldwideDisasterEvent,
        query: WorldwideDisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        if (
            query.disaster is not Disaster.LANDSLIDE
            or event.disaster is not Disaster.LANDSLIDE
        ):
            return ProviderBatch()
        return await self._get_reports(
            event,
            now=now,
            required_country_names=(),
            report_countries=(),
            country_codes=(),
        )

    async def _get_reports(
        self,
        event: DisasterEvent | WorldwideDisasterEvent,
        *,
        now: datetime,
        required_country_names: tuple[str, ...],
        report_countries: tuple[str, ...],
        country_codes: tuple[str, ...],
    ) -> ProviderBatch[SituationReport]:
        point = _event_point(event)
        if point is None:
            return ProviderBatch(issues=(_geometry_unavailable(),))
        latitude, longitude = point
        list_capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"category": "mass", "limit": "100"},
            rights_id="copernicus-data-legal-notice",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            _ACTIVATION_INFO_URL,
            params={"category": "mass", "limit": 100},
            capture=list_capture,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("results"), list
        ):
            return ProviderBatch(issues=(_invalid_schema("activation list"),))

        candidates: list[_Activation] = []
        issues: list[ProviderIssue] = []
        for index, item in enumerate(payload["results"]):
            try:
                activation = _parse_activation(
                    item,
                    event_time=event.event_time,
                    latitude=latitude,
                    longitude=longitude,
                    required_country_names=required_country_names,
                )
            except (TypeError, ValueError, OverflowError) as error:
                issues.append(_invalid_record(index, error))
                continue
            if activation is not None:
                candidates.append(activation)
        candidates.sort(
            key=lambda item: (
                abs(item.event_time - event.event_time),
                item.distance_km,
                item.code,
            )
        )
        if not candidates:
            if not issues:
                issues.append(_empty_result())
            return ProviderBatch(issues=tuple(issues))

        for activation in candidates[:_MAX_CANDIDATES]:
            detail_capture = build_snapshot_capture(
                self._snapshot_recorder,
                source_id=self.source_id,
                parameters={"code": activation.code},
                rights_id="copernicus-data-legal-notice",
                retrieved_at=now,
            )
            detail = await get_json(
                self._client,
                _ACTIVATION_DETAIL_URL,
                params={"code": activation.code},
                capture=detail_capture,
                allowed_hosts=self.allowed_hosts,
                max_bytes=self._max_response_bytes,
                provider_name=self.provider_name,
            )
            result = _detail_result(detail, activation.code)
            if result is None:
                issues.append(_invalid_schema(f"activation {activation.code}"))
                continue
            product_types = _qualifying_product_types(result)
            if not product_types:
                continue
            countries = report_countries or activation.countries
            source = SourceReference(
                source_id=self.source_id,
                publisher=("Copernicus Emergency Management Service Rapid Mapping"),
                title=activation.name,
                canonical_url=f"{_CANONICAL_ROOT}/{activation.code}",
                published_at=activation.activation_time,
                updated_at=activation.updated_at,
                retrieved_at=now,
                authority=SourceAuthority.SECONDARY,
                snapshot_id=(
                    detail_capture.snapshot.snapshot_id
                    if detail_capture and detail_capture.snapshot
                    else None
                ),
            )
            product_label = ", ".join(product_types)
            facts = (
                ReportedFact(
                    category="map_layers",
                    label="Rapid Mapping activation",
                    value=activation.code,
                    status=FactStatus.CONFIRMED,
                    source=source,
                    event_id=event.event_id,
                    observed_at=activation.event_time,
                ),
                ReportedFact(
                    category="map_layers",
                    label="Delivered crisis-mapping product types",
                    value=product_label,
                    status=FactStatus.CONFIRMED,
                    source=source,
                    event_id=event.event_id,
                    observed_at=activation.updated_at,
                ),
            )
            descriptions = {
                "DEL": "delineation",
                "GRA": "grading",
            }
            delivered = " and ".join(descriptions[item] for item in product_types)
            report = SituationReport(
                source=source,
                narrative=(
                    f"Copernicus EMS Rapid Mapping delivered a feasible {delivered} "
                    f"product for {activation.code}, {activation.name}. The activation "
                    "and mapped product are associated secondary map evidence. This "
                    "evidence does not independently prove event identity or establish "
                    "unmapped casualties, damage, or total affected area."
                ),
                facts=facts,
                event_id=event.event_id,
                correlation=CorrelationStatus.POSSIBLE,
                reported_event_time=activation.event_time,
                locations=(activation.name,),
                countries=countries,
                country_codes=country_codes,
                disaster=Disaster.LANDSLIDE,
                provider_event_ids=(f"cems:{activation.code}",),
            )
            return ProviderBatch((report,), tuple(issues))

        issues.append(_no_qualifying_product())
        return ProviderBatch(issues=tuple(issues))

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


def _parse_activation(
    value: object,
    *,
    event_time: datetime,
    latitude: float,
    longitude: float,
    required_country_names: tuple[str, ...],
) -> _Activation | None:
    if not isinstance(value, dict):
        raise TypeError("activation is not an object")
    code = _text(value.get("code"))
    if not _RAPID_CODE.fullmatch(code):
        return None
    if _text(value.get("category")).casefold() != "mass movement":
        return None
    if _positive_int(value.get("n_products")) is None:
        return None
    countries = _country_names(value.get("countries"))
    required = {_normalized_name(item) for item in required_country_names}
    if required and not required.intersection(
        _normalized_name(item) for item in countries
    ):
        return None
    mapped_time = normalize_timestamp(value.get("eventTime"))
    if mapped_time is None:
        raise ValueError("event time is missing")
    if abs(mapped_time - event_time) > _MAX_TIME_DIFFERENCE:
        return None
    mapped_point = _wkt_point(value.get("centroid"))
    if mapped_point is None:
        raise ValueError("centroid is missing")
    mapped_latitude, mapped_longitude = mapped_point
    distance = _distance_km(
        latitude,
        longitude,
        mapped_latitude,
        mapped_longitude,
    )
    if distance > _MAX_DISTANCE_KM:
        return None
    name = sanitize_provider_text(_text(value.get("name")), limit=240)
    if not name:
        raise ValueError("activation name is missing")
    return _Activation(
        code=code.upper(),
        name=name,
        countries=countries,
        event_time=mapped_time,
        activation_time=normalize_timestamp(value.get("activationTime")),
        updated_at=normalize_timestamp(value.get("lastUpdate")),
        latitude=mapped_latitude,
        longitude=mapped_longitude,
        distance_km=distance,
    )


def _detail_result(payload: object, code: str) -> dict[str, object] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return None
    for item in payload["results"]:
        if isinstance(item, dict) and _text(item.get("code")).upper() == code:
            return item
    return None


def _qualifying_product_types(detail: dict[str, object]) -> tuple[str, ...]:
    result: set[str] = set()
    aois = detail.get("aois")
    if not isinstance(aois, list):
        return ()
    for aoi in aois:
        if not isinstance(aoi, dict) or not isinstance(aoi.get("products"), list):
            continue
        for product in aoi["products"]:
            if not isinstance(product, dict):
                continue
            product_type = _text(product.get("type")).upper()
            if (
                product_type in _CRISIS_PRODUCT_TYPES
                and product.get("feasible") is True
                and _positive_int(product.get("mapsCount")) is not None
                and _is_delivered(product.get("version"))
            ):
                result.add(product_type)
    return tuple(sorted(result))


def _is_delivered(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    status = _text(value.get("status")).upper()
    status_code = _text(value.get("statusCode")).upper()
    return (
        status in {"DELIVERED", "FINAL"}
        or status_code == "F"
        or normalize_timestamp(value.get("deliveryTime")) is not None
    )


def _country_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        name = _text(item.get("name")) if isinstance(item, dict) else _text(item)
        if name:
            names.append(name)
    return tuple(dict.fromkeys(names))


def _wkt_point(value: object) -> tuple[float, float] | None:
    match = _POINT.fullmatch(_text(value))
    if match is None:
        return None
    latitude = float(match.group("latitude"))
    longitude = float(match.group("longitude"))
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("centroid is outside WGS84")
    return latitude, longitude


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalized_name(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in folded if character.isalnum())


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
        CopernicusRapidMappingAdapter.provider_name,
        "Copernicus EMS Rapid Mapping: The selected event has no source-backed "
        "point for conservative map correlation.",
        reason_code="event_geometry_unavailable",
    )


def _invalid_schema(context: str) -> ProviderIssue:
    return ProviderIssue(
        CopernicusRapidMappingAdapter.provider_name,
        "Copernicus EMS Rapid Mapping: The response had no supported schema.",
        reason_code="invalid_schema",
        detail=context,
    )


def _invalid_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        CopernicusRapidMappingAdapter.provider_name,
        "Copernicus EMS Rapid Mapping: A malformed activation was skipped.",
        reason_code="invalid_record",
        detail=f"results[{index}]: {error}",
    )


def _empty_result() -> ProviderIssue:
    return ProviderIssue(
        CopernicusRapidMappingAdapter.provider_name,
        "Copernicus EMS Rapid Mapping: No conservatively correlated Rapid Mapping "
        "activation was found.",
        reason_code="empty_result",
    )


def _no_qualifying_product() -> ProviderIssue:
    return ProviderIssue(
        CopernicusRapidMappingAdapter.provider_name,
        "Copernicus EMS Rapid Mapping: Matching activation metadata had no delivered "
        "feasible delineation or grading product.",
        reason_code="no_qualifying_mapping_product",
    )
