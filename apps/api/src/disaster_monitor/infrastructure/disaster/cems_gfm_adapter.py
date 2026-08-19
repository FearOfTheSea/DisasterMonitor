"""CEMS Global Flood Monitoring event discovery through official EODC APIs."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
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
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    SnapshotCapture,
    SourcePayloadRecorder,
    build_snapshot_capture,
    post_json,
    validate_network_target,
)

GFM_STAC_SEARCH_URL = "https://stac.eodc.eu/api/v1/search"
GFM_TITILER_STATISTICS_URL = "https://titiler.services.eodc.eu/cog/statistics"
_GFM_COLLECTION = "GFM"
_GFM_ASSET = "ensemble_flood_extent"
_GFM_RIGHTS_ID = "cems-gfm-eodc-license"
_MAX_TIME_WINDOW_DAYS = 30
_MAX_STAC_ITEMS = 50
_MAX_STATISTICS_CONCURRENCY = 6
_ALLOWED_HOSTS = frozenset({"stac.eodc.eu", "titiler.services.eodc.eu", "data.eodc.eu"})


@dataclass(frozen=True, slots=True)
class _GfmCandidate:
    item_id: str
    acquisition_id: str
    event_time: datetime
    published_at: datetime | None
    updated_at: datetime | None
    canonical_url: str
    asset_href: str
    geometry: dict[str, object]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is not an object")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("The provider clock must be timezone-aware")
    return value.astimezone(UTC)


def _time_window(time_window_days: int, *, now: datetime) -> tuple[datetime, datetime]:
    bounded_days = min(max(int(time_window_days), 1), _MAX_TIME_WINDOW_DAYS)
    end = _utc(now)
    return end - timedelta(days=bounded_days), end


def _timestamp(value: object, label: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise ValueError(f"{label} is missing")
        return None
    parsed = normalize_timestamp(value)
    if parsed is None:
        raise ValueError(f"{label} is invalid")
    return parsed


def country_geojson(country: Country) -> dict[str, object]:
    """Translate catalog polygons from stored (latitude, longitude) to GeoJSON."""
    polygons: list[list[list[list[float]]]] = []
    for polygon in country.geographic_area.polygons:
        if len(polygon) < 3:
            raise ValueError("The country has no usable polygon")
        ring: list[list[float]] = []
        for latitude, longitude in polygon:
            if (
                isinstance(latitude, bool)
                or isinstance(longitude, bool)
                or not isinstance(latitude, (int, float))
                or not isinstance(longitude, (int, float))
                or not isfinite(latitude)
                or not isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                raise ValueError("The country polygon has invalid coordinates")
            ring.append([float(longitude), float(latitude)])
        if ring[0] != ring[-1]:
            ring.append(ring[0].copy())
        polygons.append([ring])
    if not polygons:
        raise ValueError("The country has no usable polygon")
    return {"type": "MultiPolygon", "coordinates": polygons}


def build_gfm_search_payload(
    query: DisasterQuery | WorldwideDisasterQuery,
    *,
    now: datetime,
    country_geometry: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build one deterministic, bounded EODC STAC search body."""
    start, end = _time_window(query.time_window_days, now=now)
    body: dict[str, object] = {
        "collections": [_GFM_COLLECTION],
        "datetime": f"{start.isoformat().replace('+00:00', 'Z')}"
        f"/{end.isoformat().replace('+00:00', 'Z')}",
        "limit": min(
            _MAX_STAC_ITEMS,
            max(1, query.limit)
            if isinstance(query, WorldwideDisasterQuery)
            else _MAX_STAC_ITEMS,
        ),
        "sortby": [{"field": "datetime", "direction": "desc"}],
    }
    if country_geometry is None:
        body["bbox"] = [-180.0, -90.0, 180.0, 90.0]
    else:
        body["intersects"] = country_geometry
    return body


class CemsGfmAdapter:
    """Discover only GFM acquisitions with nonzero country-clipped flood pixels."""

    provider_name = "CEMS Global Flood Monitoring (GFM)"
    source_id = "cems-gfm-floods"
    allowed_hosts = _ALLOWED_HOSTS

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

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if not isinstance(query, DisasterQuery) or query.disaster is not Disaster.FLOOD:
            return ProviderBatch()
        if self._geography is None:
            return ProviderBatch(issues=(_country_projection_unusable(-1),))
        country = self._geography.get_by_alpha3(query.country.alpha3_code)
        if country is None:
            return ProviderBatch(issues=(_country_projection_unusable(-1),))
        try:
            geometry = country_geojson(country)
        except ValueError:
            return ProviderBatch(issues=(_country_projection_unusable(-1),))
        result = await self._find(
            query, now=now, country=query.country, geometry=geometry
        )
        return ProviderBatch(
            records=tuple(
                item for item in result.records if isinstance(item, DisasterEvent)
            ),
            issues=result.issues,
        )

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[WorldwideDisasterEvent]:
        if not isinstance(query, WorldwideDisasterQuery):
            return ProviderBatch()
        if query.disaster is not Disaster.FLOOD or query.limit <= 0:
            return ProviderBatch()
        result = await self._find(query, now=now, country=None, geometry=None)
        return ProviderBatch(
            records=tuple(
                item
                for item in result.records
                if isinstance(item, WorldwideDisasterEvent)
            ),
            issues=result.issues,
        )

    async def _find(
        self,
        query: DisasterQuery | WorldwideDisasterQuery,
        *,
        now: datetime,
        country: Country | None,
        geometry: dict[str, object] | None,
    ) -> ProviderBatch[DisasterEvent | WorldwideDisasterEvent]:
        search_body = build_gfm_search_payload(
            query, now=now, country_geometry=geometry
        )
        search_capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "operation": "stac-search",
                "collection": _GFM_COLLECTION,
                "scope": country.alpha3_code if country else "worldwide",
                "from": str(search_body["datetime"]).partition("/")[0],
                "to": str(search_body["datetime"]).partition("/")[2],
                "limit": str(search_body["limit"]),
            },
            rights_id=_GFM_RIGHTS_ID,
            retrieved_at=_utc(now),
        )
        payload = await post_json(
            self._client,
            GFM_STAC_SEARCH_URL,
            json_body=search_body,
            capture=search_capture,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
        )
        features = self._features(payload)
        if not features:
            return ProviderBatch(issues=(_empty_result(),))

        start, end = _time_window(query.time_window_days, now=now)
        records: dict[str, DisasterEvent | WorldwideDisasterEvent] = {}
        issues: list[ProviderIssue] = []
        candidates: list[tuple[int, _GfmCandidate]] = []
        for index, raw_feature in enumerate(features[:_MAX_STAC_ITEMS]):
            try:
                candidate = self._candidate(
                    raw_feature, start=start, end=end, index=index
                )
            except ValueError as error:
                issues.append(_invalid_record(index, error))
                continue
            candidates.append((index, candidate))

        semaphore = asyncio.Semaphore(_MAX_STATISTICS_CONCURRENCY)
        inspections = await asyncio.gather(
            *(
                self._inspect_candidate(
                    index,
                    candidate,
                    now=now,
                    country=country,
                    geometry=geometry,
                    search_capture=search_capture,
                    semaphore=semaphore,
                )
                for index, candidate in candidates
            )
        )
        for (_index, candidate), (positive, snapshot_id, issue) in zip(
            candidates, inspections, strict=True
        ):
            if issue is not None:
                issues.append(issue)
            if not positive:
                continue
            source = SourceReference(
                source_id=self.source_id,
                publisher="Copernicus Emergency Management Service (CEMS) / EODC",
                title=f"GFM Observed Flood Extent — {candidate.item_id}",
                canonical_url=candidate.canonical_url,
                published_at=candidate.published_at,
                updated_at=candidate.updated_at,
                retrieved_at=_utc(now),
                authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
                snapshot_id=snapshot_id,
            )
            event_id = f"cems-gfm:sentinel-acquisition:{candidate.acquisition_id}"
            provider_ids = (event_id, f"cems-gfm:item:{candidate.item_id}")
            if country is None:
                event: DisasterEvent | WorldwideDisasterEvent = WorldwideDisasterEvent(
                    event_id=event_id,
                    disaster=Disaster.FLOOD,
                    location=f"CEMS GFM acquisition {candidate.acquisition_id}",
                    event_time=candidate.event_time,
                    source=source,
                    provider_ids=provider_ids,
                )
            else:
                event = DisasterEvent(
                    event_id=event_id,
                    disaster=Disaster.FLOOD,
                    location=country.canonical_name,
                    country=country,
                    event_time=candidate.event_time,
                    source=source,
                    provider_ids=provider_ids,
                    geography_status=EventGeographyStatus.IN_COUNTRY,
                )
            existing = records.get(event_id)
            if existing is None:
                records[event_id] = event
            else:
                records[event_id] = replace(
                    existing,
                    provider_ids=(*existing.provider_ids, *event.provider_ids[1:]),
                )
        return ProviderBatch(records=tuple(records.values()), issues=tuple(issues))

    async def _inspect_candidate(
        self,
        index: int,
        candidate: _GfmCandidate,
        *,
        now: datetime,
        country: Country | None,
        geometry: dict[str, object] | None,
        search_capture: SnapshotCapture | None,
        semaphore: asyncio.Semaphore,
    ) -> tuple[bool, str | None, ProviderIssue | None]:
        """Check one candidate while retaining typed per-item failures."""
        stats_body = {
            "type": "Feature",
            "geometry": geometry or candidate.geometry,
            "properties": {},
        }
        stats_capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "operation": "clipped-statistics",
                "scope": country.alpha3_code if country else "worldwide",
                "item": candidate.item_id,
                "asset": candidate.asset_href,
            },
            rights_id=_GFM_RIGHTS_ID,
            retrieved_at=_utc(now),
        )
        async with semaphore:
            try:
                statistics = await post_json(
                    self._client,
                    GFM_TITILER_STATISTICS_URL,
                    params={
                        "url": candidate.asset_href,
                        "bidx": 1,
                        "categorical": True,
                        "c": 1,
                        "max_size": 1024,
                    },
                    json_body=stats_body,
                    capture=stats_capture,
                    allowed_hosts=self.allowed_hosts,
                    max_bytes=self._max_response_bytes,
                    provider_name=self.provider_name,
                )
            except DisasterProviderError as error:
                return False, None, _provider_failure(index, error)
        try:
            positive = _has_observed_flood_class_one(statistics)
        except ValueError as error:
            return False, None, _invalid_record(index, error)
        snapshot_id = (
            stats_capture.snapshot.snapshot_id
            if stats_capture and stats_capture.snapshot
            else search_capture.snapshot.snapshot_id
            if search_capture and search_capture.snapshot
            else None
        )
        return positive, snapshot_id, None

    def _features(self, payload: object) -> list[object]:
        document = _mapping(payload, "STAC response")
        if _text(document.get("type")) != "FeatureCollection":
            raise DisasterProviderResponseError(
                "The EODC STAC response was not a FeatureCollection.",
                reason_code="invalid_schema",
            )
        features = document.get("features")
        if not isinstance(features, list):
            raise DisasterProviderResponseError(
                "The EODC STAC response had no feature list.",
                reason_code="invalid_schema",
            )
        return features

    def _candidate(
        self,
        raw_feature: object,
        *,
        start: datetime,
        end: datetime,
        index: int,
    ) -> _GfmCandidate:
        feature = _mapping(raw_feature, f"feature[{index}]")
        if _text(feature.get("type")) != "Feature":
            raise ValueError("feature type is invalid")
        collection = feature.get("collection")
        if not (
            _text(collection) == _GFM_COLLECTION
            or isinstance(collection, list)
            and _GFM_COLLECTION in collection
        ):
            raise ValueError("feature collection is not GFM")
        item_id = _text(feature.get("id"))
        properties = _mapping(feature.get("properties"), f"feature[{index}].properties")
        acquisition_id = _text(properties.get("parent"))
        event_time = _timestamp(
            properties.get("datetime"), "item datetime", required=True
        )
        assert event_time is not None
        if not start <= event_time <= end:
            raise ValueError("item datetime is outside the bounded query window")
        if not item_id or not acquisition_id:
            raise ValueError("item or Sentinel acquisition identity is missing")
        geometry = _geometry(feature.get("geometry"), f"feature[{index}].geometry")
        assets = _mapping(feature.get("assets"), f"feature[{index}].assets")
        asset = _mapping(assets.get(_GFM_ASSET), f"asset {_GFM_ASSET}")
        asset_href = _text(asset.get("href"))
        if not asset_href:
            raise ValueError("ensemble_flood_extent asset is missing")
        try:
            validate_network_target(asset_href, self.allowed_hosts)
        except DisasterProviderResponseError as error:
            raise ValueError(error.failure.reason_code) from error
        item_url = self._item_url(item_id, feature.get("links"))
        return _GfmCandidate(
            item_id=item_id,
            acquisition_id=acquisition_id,
            event_time=event_time,
            published_at=_timestamp(properties.get("created"), "item created"),
            updated_at=_timestamp(
                properties.get("processing:datetime"), "processing datetime"
            ),
            canonical_url=item_url,
            asset_href=asset_href,
            geometry=geometry,
        )

    def _item_url(self, item_id: str, links: object) -> str:
        if isinstance(links, list):
            for raw_link in links:
                if not isinstance(raw_link, Mapping):
                    continue
                if _text(raw_link.get("rel")) != "self":
                    continue
                href = _text(raw_link.get("href"))
                try:
                    validate_network_target(href, self.allowed_hosts)
                except DisasterProviderResponseError:
                    continue
                return href
        return (
            "https://stac.eodc.eu/api/v1/collections/GFM/items/"
            f"{quote(item_id, safe='')}"
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _geometry(value: object, label: str) -> dict[str, object]:
    geometry = dict(_mapping(value, label))
    if _text(geometry.get("type")) not in {"Polygon", "MultiPolygon"}:
        raise ValueError(f"{label} is not a supported polygon")
    if not isinstance(geometry.get("coordinates"), list):
        raise ValueError(f"{label} coordinates are missing")
    return geometry


def _has_observed_flood_class_one(payload: object) -> bool:
    document = _mapping(payload, "statistics response")
    if _text(document.get("type")) == "Feature":
        features = [document]
    elif _text(document.get("type")) == "FeatureCollection":
        raw_features = document.get("features")
        if not isinstance(raw_features, list):
            raise ValueError("statistics feature list is missing")
        features = [_mapping(item, "statistics feature") for item in raw_features]
    else:
        raise ValueError("statistics response is not GeoJSON")
    for feature in features:
        properties = _mapping(feature.get("properties"), "statistics properties")
        statistics = _mapping(properties.get("statistics"), "statistics")
        band = statistics.get("b1") or statistics.get(_GFM_ASSET)
        band_mapping = _mapping(band, "ensemble_flood_extent statistics")
        histogram = band_mapping.get("histogram")
        if (
            not isinstance(histogram, list)
            or len(histogram) != 2
            or not isinstance(histogram[0], list)
            or not isinstance(histogram[1], list)
            or len(histogram[0]) != len(histogram[1])
        ):
            raise ValueError("statistics histogram is missing or malformed")
        for count, category in zip(histogram[0], histogram[1], strict=True):
            if (
                isinstance(category, (int, float))
                and not isinstance(category, bool)
                and isfinite(category)
                and category == 1
                and isinstance(count, (int, float))
                and not isinstance(count, bool)
                and isfinite(count)
                and count > 0
            ):
                return True
    return False


def _invalid_record(index: int, error: Exception) -> ProviderIssue:
    return ProviderIssue(
        CemsGfmAdapter.provider_name,
        "CEMS GFM: A malformed or unauthorized acquisition record was skipped.",
        reason_code=(
            "source_policy_violation"
            if str(error) == "source_policy_violation"
            else "invalid_record"
        ),
        detail=f"feature[{index}]: {error}",
    )


def _provider_failure(index: int, error: DisasterProviderError) -> ProviderIssue:
    failure = error.failure
    return ProviderIssue(
        CemsGfmAdapter.provider_name,
        "CEMS GFM: One clipped statistics request failed.",
        reason_code=failure.reason_code,
        retryable=failure.retryable,
        http_status=failure.http_status,
        detail=f"feature[{index}]: {failure.detail or str(error)}",
    )


def _country_projection_unusable(index: int) -> ProviderIssue:
    return ProviderIssue(
        CemsGfmAdapter.provider_name,
        "CEMS GFM: The country has no usable polygon for clipped flood statistics.",
        reason_code="country_projection_unusable",
        detail=(
            "country catalog projection unavailable"
            if index < 0
            else f"feature[{index}] has no usable country projection"
        ),
    )


def _empty_result() -> ProviderIssue:
    return ProviderIssue(
        CemsGfmAdapter.provider_name,
        "CEMS GFM: The provider returned no matching records.",
        reason_code="empty_result",
    )
