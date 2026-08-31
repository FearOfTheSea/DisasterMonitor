"""Official NHC/CPHC forecast track and uncertainty geometry."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from io import BytesIO
from math import isfinite
from xml.etree.ElementTree import Element
from zipfile import BadZipFile, ZipFile

import httpx
from defusedxml import ElementTree

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    CycloneMapCoordinate,
    CycloneMapGeometryKind,
    CycloneMapLayer,
    CycloneMapSemanticRole,
    Disaster,
    DisasterEvent,
    EventCoordinate,
    EventGeometryKind,
    SituationReport,
    SourceAuthority,
    SourceReference,
    geographic_distance_km,
)
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError
from disaster_monitor.infrastructure.disaster.http import (
    SnapshotCapture,
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_bytes,
    get_text,
)

_FEED_URLS = (
    "https://www.nhc.noaa.gov/gis-at.xml",
    "https://www.nhc.noaa.gov/gis-ep.xml",
    "https://www.nhc.noaa.gov/gis-cp.xml",
)
_GDACS_SOURCE_ID = "gdacs-tropical-cyclones"
_RIGHTS_ID = "noaa-nws-public-domain"
_MAX_FEED_ITEMS = 30
_MAX_CANDIDATES = 5
_MAX_TRACK_POINTS = 20
_MAX_CONE_POINTS = 5_000
_MAX_ARCHIVE_ENTRIES = 20
_MAX_UNCOMPRESSED_BYTES = 1_000_000
_MAX_MATCH_DISTANCE_KM = 500.0
_STORM_ID = re.compile(r"\b([A-Z]{2}\d{6})\b", re.IGNORECASE)
_ADVISORY = re.compile(r"Advisory\s+#(\d{1,3})", re.IGNORECASE)
_FORECAST_HOUR = re.compile(r"\b(\d{1,3})\s*hr\s+Forecast\b", re.IGNORECASE)
_VALID_AT = re.compile(
    r"Valid\s+at:\s*(\d{1,2}:\d{2}\s+[AP]M)\s+([A-Z]{2,4})\s+"
    r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
_CONE_TIME = re.compile(
    r"(\d{3,4})\s*([AP]M)\s+([A-Z]{2,4})\s+(?:[A-Za-z]{3}\s+)?"
    r"([A-Za-z]{3}\s+\d{1,2}\s+\d{4})",
    re.IGNORECASE,
)
_ZONE_OFFSETS = {
    "HST": -10,
    "HDT": -9,
    "PST": -8,
    "PDT": -7,
    "MST": -7,
    "MDT": -6,
    "CST": -6,
    "CDT": -5,
    "EST": -5,
    "EDT": -4,
    "AST": -4,
    "ADT": -3,
}


@dataclass(frozen=True, slots=True)
class _Product:
    kind: str
    url: str
    published_at: datetime
    advisory: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    storm_id: str
    name: str
    latitude: float
    longitude: float
    published_at: datetime
    feed_url: str
    feed_capture: SnapshotCapture | None
    products: tuple[_Product, ...]


class NhcCycloneForecastAdapter:
    """Reconcile official NHC forecast products to one selected GDACS storm."""

    provider_name = "NOAA NHC/CPHC cyclone forecasts"
    source_id = "noaa-nhc-cyclone-forecast"
    allowed_hosts = frozenset({"www.nhc.noaa.gov"})

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
        event_point = _event_point(event)
        if event_point is None:
            return ProviderBatch(issues=(_geometry_unavailable(),))

        candidates: list[_Candidate] = []
        issues: list[ProviderIssue] = []
        for feed_url in _FEED_URLS:
            capture = self._capture(feed_url, now)
            feed_payload = await get_text(
                self._client,
                feed_url,
                capture=capture,
                allowed_hosts=self.allowed_hosts,
                max_bytes=self._max_response_bytes,
                provider_name=self.provider_name,
            )
            parsed, feed_issues = _parse_feed(feed_payload, feed_url, capture)
            candidates.extend(parsed)
            issues.extend(feed_issues)

        candidates = list(_deduplicate_candidates(candidates))
        name_tokens = _name_tokens(event.source.title)
        matches = [
            candidate
            for candidate in candidates
            if _normalized_name(candidate.name) in name_tokens
            and geographic_distance_km(
                event_point,
                EventCoordinate(candidate.latitude, candidate.longitude),
            )
            <= _MAX_MATCH_DISTANCE_KM
        ]
        if len(matches) != 1:
            issues.append(_identity_issue(ambiguous=len(matches) > 1))
            return ProviderBatch(issues=tuple(issues))

        candidate = matches[0]
        if not candidate.products:
            issues.append(_products_unavailable())
            return ProviderBatch(issues=tuple(issues))

        layers: list[CycloneMapLayer] = []
        for product in candidate.products:
            capture = self._capture(product.url, now)
            try:
                product_payload = await get_bytes(
                    self._client,
                    product.url,
                    capture=capture,
                    allowed_hosts=self.allowed_hosts,
                    max_bytes=self._max_response_bytes,
                    provider_name=self.provider_name,
                )
                kml = _extract_kml(product_payload)
                source = _product_source(candidate, product, capture, now)
                if product.kind == "track":
                    layer, product_issues = _parse_track(
                        kml, candidate, product, source
                    )
                else:
                    layer, product_issues = _parse_cone(kml, candidate, product, source)
                issues.extend(product_issues)
                if layer is not None:
                    layers.append(layer)
            except DisasterProviderError as error:
                issues.append(_provider_error(product.kind, error))
            except (BadZipFile, ElementTree.ParseError, ValueError) as error:
                issues.append(_invalid_product(product.kind, error))

        if not layers:
            return ProviderBatch(issues=tuple(issues))

        layers.sort(key=lambda item: item.semantic_role.value)
        source = _feed_source(candidate, now)
        distance = geographic_distance_km(
            event_point, EventCoordinate(candidate.latitude, candidate.longitude)
        )
        report = SituationReport(
            source=source,
            narrative=(
                f"NOAA NHC/CPHC advisory products for {candidate.name} "
                f"({candidate.storm_id}) were reconciled by unique storm name and "
                f"source-backed center proximity ({distance:.0f} km). Forecast and "
                "uncertainty layers are advisory products, not observed footprints."
            ),
            event_id=event.event_id,
            correlation=CorrelationStatus.MATCHED,
            reported_event_time=event.event_time,
            locations=(event.location,),
            countries=countries,
            country_codes=country_codes,
            disaster=Disaster.TROPICAL_CYCLONE,
            provider_event_ids=(f"atcf:{candidate.storm_id}",),
            supplemental_geometry=tuple(layers),
        )
        return ProviderBatch((report,), tuple(issues))

    def _capture(self, url: str, now: datetime) -> SnapshotCapture | None:
        return build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"url": url},
            rights_id=_RIGHTS_ID,
            retrieved_at=now,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _eligible(
    event: DisasterEvent | WorldwideDisasterEvent, query_disaster: Disaster
) -> bool:
    return (
        query_disaster is Disaster.TROPICAL_CYCLONE
        and event.disaster is Disaster.TROPICAL_CYCLONE
        and event.source.source_id == _GDACS_SOURCE_ID
    )


def _event_point(
    event: DisasterEvent | WorldwideDisasterEvent,
) -> EventCoordinate | None:
    geometry = event.geometry
    if (
        geometry is None
        or geometry.kind is not EventGeometryKind.POINT
        or len(geometry.coordinates) != 1
    ):
        return None
    return geometry.coordinates[0]


def _parse_feed(
    payload: str,
    feed_url: str,
    capture: SnapshotCapture | None,
) -> tuple[tuple[_Candidate, ...], tuple[ProviderIssue, ...]]:
    if "<!DOCTYPE" in payload.upper() or "<!ENTITY" in payload.upper():
        raise ValueError("XML declarations are not supported")
    root = ElementTree.fromstring(payload)
    items = list(root.iter("item"))
    issues: list[ProviderIssue] = []
    if len(items) > _MAX_FEED_ITEMS:
        issues.append(_result_limit("feed item"))
        items = items[:_MAX_FEED_ITEMS]

    summaries: dict[str, tuple[str, float, float, datetime]] = {}
    products: dict[str, list[_Product]] = {}
    for index, item in enumerate(items):
        title = _child_text(item, "title")
        if title.startswith("Summary -"):
            try:
                storm_id = _storm_id(title) or _descendant_text(item, "atcf")
                name = _descendant_text(item, "name")
                center = _descendant_text(item, "center")
                published_at = _rss_time(_child_text(item, "pubDate"))
                latitude_text, longitude_text = center.split(",", maxsplit=1)
                latitude, longitude = float(latitude_text), float(longitude_text)
                EventCoordinate(latitude, longitude)
                if not storm_id or not name:
                    raise ValueError("summary identity is incomplete")
                summaries[storm_id] = (name, latitude, longitude, published_at)
            except (TypeError, ValueError, OverflowError) as error:
                issues.append(_invalid_feed_record(index, error))
            continue

        kind = _product_kind(title)
        if kind is None:
            continue
        try:
            storm_id = _storm_id(title)
            url = _child_text(item, "link")
            published_at = _rss_time(_child_text(item, "pubDate"))
            advisory_match = _ADVISORY.search(title)
            if not storm_id or not url or advisory_match is None:
                raise ValueError("product identity is incomplete")
            products.setdefault(storm_id, []).append(
                _Product(kind, url, published_at, advisory_match.group(1).zfill(3))
            )
        except (TypeError, ValueError) as error:
            issues.append(_invalid_feed_record(index, error))

    candidates: list[_Candidate] = []
    for storm_id, (name, latitude, longitude, published_at) in summaries.items():
        selected_products: list[_Product] = []
        for kind in ("track", "cone"):
            options = sorted(
                (item for item in products.get(storm_id, ()) if item.kind == kind),
                key=lambda item: (item.published_at, item.advisory, item.url),
            )
            if options:
                selected_products.append(options[-1])
        candidates.append(
            _Candidate(
                storm_id,
                name,
                latitude,
                longitude,
                published_at,
                feed_url,
                capture,
                tuple(selected_products),
            )
        )
    candidates.sort(key=lambda item: item.storm_id)
    if len(candidates) > _MAX_CANDIDATES:
        issues.append(_result_limit("active storm"))
        candidates = candidates[:_MAX_CANDIDATES]
    return tuple(candidates), tuple(issues)


def _deduplicate_candidates(candidates: list[_Candidate]) -> tuple[_Candidate, ...]:
    selected: dict[str, _Candidate] = {}
    for candidate in sorted(
        candidates,
        key=lambda item: (item.published_at, item.feed_url),
    ):
        selected[candidate.storm_id] = candidate
    return tuple(selected[key] for key in sorted(selected))


def _extract_kml(payload: bytes) -> bytes:
    with ZipFile(BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > _MAX_ARCHIVE_ENTRIES:
            raise ValueError("archive entry limit exceeded")
        if any(item.flag_bits & 0x1 for item in entries):
            raise ValueError("encrypted archive entries are unsupported")
        if sum(item.file_size for item in entries) > _MAX_UNCOMPRESSED_BYTES:
            raise ValueError("archive expansion limit exceeded")
        kml_entries = [
            item for item in entries if item.filename.lower().endswith(".kml")
        ]
        if len(kml_entries) != 1:
            raise ValueError("archive must contain exactly one KML document")
        return archive.read(kml_entries[0])


def _parse_track(
    payload: bytes,
    candidate: _Candidate,
    product: _Product,
    source: SourceReference,
) -> tuple[CycloneMapLayer | None, tuple[ProviderIssue, ...]]:
    root = _parse_kml(payload)
    coordinates: list[CycloneMapCoordinate] = []
    issues: list[ProviderIssue] = []
    for index, placemark in enumerate(_elements(root, "Placemark")):
        description = _descendant_text(placemark, "description")
        if _FORECAST_HOUR.search(description) is None:
            continue
        try:
            valid_at = _track_time(description)
            point = next(_elements(placemark, "Point"))
            coordinate_text = _descendant_text(point, "coordinates")
            latitude, longitude = _coordinate(coordinate_text)
            coordinates.append(CycloneMapCoordinate(latitude, longitude, valid_at))
        except (StopIteration, TypeError, ValueError, OverflowError) as error:
            issues.append(_invalid_product_record("track", index, error))
        if len(coordinates) >= _MAX_TRACK_POINTS:
            issues.append(_result_limit("forecast track point"))
            break
    unique = tuple(
        sorted(
            set(coordinates),
            key=lambda item: (
                item.valid_at or datetime.min.replace(tzinfo=UTC),
                item.latitude,
                item.longitude,
            ),
        )
    )
    if len(unique) < 2:
        issues.append(
            _invalid_product("track", ValueError("fewer than two valid points"))
        )
        return None, tuple(issues)
    layer = CycloneMapLayer(
        layer_id=f"noaa-nhc:{candidate.storm_id}:advisory-{product.advisory}:forecast-track",
        semantic_role=CycloneMapSemanticRole.FORECAST_TRACK,
        geometry_kind=CycloneMapGeometryKind.TRACK,
        coordinates=unique,
        source=source,
        issued_at=product.published_at,
        valid_from=unique[0].valid_at,
        valid_to=unique[-1].valid_at,
        storm_id=candidate.storm_id,
        provisional=False,
        limitation=(
            "The forecast track contains exact official forecast positions; "
            "connecting segments are not an observed storm footprint."
        ),
        reconciliation=(
            "Matched to the selected GDACS cyclone by unique storm name and "
            "source-backed center proximity."
        ),
    )
    return layer, tuple(issues)


def _parse_cone(
    payload: bytes,
    candidate: _Candidate,
    product: _Product,
    source: SourceReference,
) -> tuple[CycloneMapLayer | None, tuple[ProviderIssue, ...]]:
    root = _parse_kml(payload)
    try:
        polygon = next(_elements(root, "Polygon"))
        coordinate_text = _descendant_text(polygon, "coordinates")
        raw_coordinates = coordinate_text.split()
        if len(raw_coordinates) > _MAX_CONE_POINTS:
            raise ValueError("uncertainty coordinate limit exceeded")
        coordinates = tuple(
            CycloneMapCoordinate(*_coordinate(item)) for item in raw_coordinates
        )
        values = {
            element.attrib.get("name", ""): _descendant_text(element, "value")
            for element in _elements(root, "Data")
        }
        if values.get("atcfid", "").upper() != candidate.storm_id:
            raise ValueError("uncertainty product storm identity differs")
        valid_from = _cone_advisory_time(values.get("advisoryDate", ""))
        forecast_period = int(values.get("fcstpd", ""))
        if not 1 <= forecast_period <= 120:
            raise ValueError("uncertainty forecast period is invalid")
        layer = CycloneMapLayer(
            layer_id=f"noaa-nhc:{candidate.storm_id}:advisory-{product.advisory}:uncertainty-area",
            semantic_role=CycloneMapSemanticRole.UNCERTAINTY_AREA,
            geometry_kind=CycloneMapGeometryKind.AREA,
            coordinates=coordinates,
            source=source,
            issued_at=product.published_at,
            valid_from=valid_from,
            valid_to=valid_from + timedelta(hours=forecast_period),
            storm_id=candidate.storm_id,
            provisional=False,
            limitation=(
                "The official cone depicts forecast track uncertainty and is not "
                "an observed storm footprint or an impact boundary."
            ),
            reconciliation=(
                "Matched to the selected GDACS cyclone by unique storm name and "
                "source-backed center proximity."
            ),
        )
    except (StopIteration, TypeError, ValueError, OverflowError) as error:
        return None, (_invalid_product("cone", error),)
    return layer, ()


def _parse_kml(payload: bytes) -> Element:
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("XML declarations are not supported")
    return ElementTree.fromstring(payload)


def _elements(root: Element, local_name: str) -> Iterator[Element]:
    return (
        element
        for element in root.iter()
        if element.tag.rsplit("}", maxsplit=1)[-1] == local_name
    )


def _child_text(element: Element, local_name: str) -> str:
    for child in element:
        if child.tag.rsplit("}", maxsplit=1)[-1] == local_name:
            return (child.text or "").strip()
    return ""


def _descendant_text(element: Element, local_name: str) -> str:
    for child in element.iter():
        if child.tag.rsplit("}", maxsplit=1)[-1] == local_name:
            return "".join(child.itertext()).strip()
    return ""


def _product_kind(title: str) -> str | None:
    lowered = title.lower()
    if "forecast track [kmz]" in lowered:
        return "track"
    if "cone of uncertainty [kmz]" in lowered:
        return "cone"
    return None


def _storm_id(value: str) -> str:
    match = _STORM_ID.search(value)
    return match.group(1).upper() if match else ""


def _rss_time(value: str) -> datetime:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _track_time(description: str) -> datetime:
    match = _VALID_AT.search(description)
    if match is None:
        raise ValueError("forecast validity time is missing")
    zone = match.group(2).upper()
    offset = _ZONE_OFFSETS.get(zone)
    if offset is None:
        raise ValueError("forecast timezone is unsupported")
    parsed = datetime.strptime(
        f"{match.group(1)} {match.group(3)}", "%I:%M %p %B %d, %Y"
    )
    return parsed.replace(tzinfo=timezone(timedelta(hours=offset))).astimezone(UTC)


def _cone_advisory_time(value: str) -> datetime:
    match = _CONE_TIME.search(value)
    if match is None:
        raise ValueError("uncertainty validity time is missing")
    clock = match.group(1).zfill(4)
    hour, minute = int(clock[:-2]), int(clock[-2:])
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        raise ValueError("uncertainty clock is invalid")
    zone = match.group(3).upper()
    offset = _ZONE_OFFSETS.get(zone)
    if offset is None:
        raise ValueError("uncertainty timezone is unsupported")
    parsed = datetime.strptime(match.group(4), "%b %d %Y").replace(
        hour=hour % 12 + (12 if match.group(2).upper() == "PM" else 0),
        minute=minute,
        tzinfo=timezone(timedelta(hours=offset)),
    )
    return parsed.astimezone(UTC)


def _coordinate(value: str) -> tuple[float, float]:
    fields = value.strip().split(",")
    if len(fields) < 2:
        raise ValueError("coordinate is incomplete")
    longitude, latitude = float(fields[0]), float(fields[1])
    if not isfinite(latitude) or not isfinite(longitude):
        raise ValueError("coordinate is not finite")
    EventCoordinate(latitude, longitude)
    return latitude, longitude


def _name_tokens(value: str) -> frozenset[str]:
    return frozenset(
        _normalized_name(token)
        for token in re.findall(r"[A-Za-z][A-Za-z_-]*", value)
        if _normalized_name(token)
    )


def _normalized_name(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _feed_source(candidate: _Candidate, now: datetime) -> SourceReference:
    return SourceReference(
        source_id=NhcCycloneForecastAdapter.source_id,
        publisher="NOAA National Hurricane Center / Central Pacific Hurricane Center",
        title=f"NHC GIS advisory summary for {candidate.name}",
        canonical_url=candidate.feed_url,
        published_at=candidate.published_at,
        updated_at=candidate.published_at,
        retrieved_at=now,
        authority=SourceAuthority.NATIONAL_AUTHORITY,
        snapshot_id=(
            candidate.feed_capture.snapshot.snapshot_id
            if candidate.feed_capture and candidate.feed_capture.snapshot
            else None
        ),
    )


def _product_source(
    candidate: _Candidate,
    product: _Product,
    capture: SnapshotCapture | None,
    now: datetime,
) -> SourceReference:
    label = "forecast track" if product.kind == "track" else "cone of uncertainty"
    return SourceReference(
        source_id=NhcCycloneForecastAdapter.source_id,
        publisher="NOAA National Hurricane Center / Central Pacific Hurricane Center",
        title=(f"NHC advisory #{product.advisory} {label} for {candidate.name}"),
        canonical_url=product.url,
        published_at=product.published_at,
        updated_at=product.published_at,
        retrieved_at=now,
        authority=SourceAuthority.NATIONAL_AUTHORITY,
        snapshot_id=capture.snapshot.snapshot_id
        if capture and capture.snapshot
        else None,
    )


def _geometry_unavailable() -> ProviderIssue:
    return ProviderIssue(
        NhcCycloneForecastAdapter.provider_name,
        "NOAA NHC/CPHC: The selected cyclone has no source-backed point for "
        "forecast reconciliation.",
        reason_code="event_geometry_unavailable",
    )


def _identity_issue(*, ambiguous: bool) -> ProviderIssue:
    return ProviderIssue(
        NhcCycloneForecastAdapter.provider_name,
        (
            "NOAA NHC/CPHC: Multiple active storms met the conservative identity rules."
            if ambiguous
            else "NOAA NHC/CPHC: The selected storm is outside current supported "
            "basin products or had no unique active match."
        ),
        reason_code="identity_not_reconciled"
        if ambiguous
        else "forecast_not_applicable",
    )


def _products_unavailable() -> ProviderIssue:
    return ProviderIssue(
        NhcCycloneForecastAdapter.provider_name,
        "NOAA NHC/CPHC: No supported forecast-track or cone KMZ was published for "
        "the matched storm.",
        reason_code="forecast_products_unavailable",
    )


def _provider_error(kind: str, error: DisasterProviderError) -> ProviderIssue:
    failure = error.failure
    return ProviderIssue(
        NhcCycloneForecastAdapter.provider_name,
        f"NOAA NHC/CPHC: The {kind} product could not be retrieved safely.",
        reason_code=failure.reason_code,
        retryable=failure.retryable,
        http_status=failure.http_status,
        detail=failure.detail,
    )


def _invalid_feed_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        NhcCycloneForecastAdapter.provider_name,
        "NOAA NHC/CPHC: A malformed feed item was skipped.",
        reason_code="invalid_product_record",
        detail=f"item[{index}]: {error}",
    )


def _invalid_product_record(kind: str, index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        NhcCycloneForecastAdapter.provider_name,
        f"NOAA NHC/CPHC: A malformed {kind} geometry record was skipped.",
        reason_code="invalid_product_record",
        detail=f"record[{index}]: {error}",
    )


def _invalid_product(kind: str, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        NhcCycloneForecastAdapter.provider_name,
        f"NOAA NHC/CPHC: The {kind} product had no safely renderable geometry.",
        reason_code="invalid_product",
        detail=str(error),
    )


def _result_limit(kind: str) -> ProviderIssue:
    return ProviderIssue(
        NhcCycloneForecastAdapter.provider_name,
        f"NOAA NHC/CPHC: The bounded {kind} limit was reached.",
        reason_code="result_limit_reached",
    )
