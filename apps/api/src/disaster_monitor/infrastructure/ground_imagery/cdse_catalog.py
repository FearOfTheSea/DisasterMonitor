"""Bounded public CDSE STAC acquisition discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from disaster_monitor.application.ports.ground_imagery.catalog import (
    CatalogSearchError,
    GroundImageryCatalogPage,
    GroundImageryCatalogQuery,
)
from disaster_monitor.domain.imagery.observations import (
    AcquisitionIdentity,
    CaptureInterval,
    Observation,
    ObservationReadiness,
    Sensor,
)
from disaster_monitor.domain.imagery.regions import polygon_from_geojson

DEFAULT_CDSE_STAC_URL = "https://stac.dataspace.copernicus.eu/v1/search"
_ALLOWED_HOST = "stac.dataspace.copernicus.eu"
_MAX_PAGE_BYTES = 8 * 1024 * 1024


class CDSEStacCatalog:
    """Discover Sentinel products without opening provider asset URLs."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_CDSE_STAC_URL,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
        maximum_response_bytes: int = _MAX_PAGE_BYTES,
    ) -> None:
        _validate_endpoint(endpoint)
        if not 10_000 <= maximum_response_bytes <= _MAX_PAGE_BYTES:
            raise ValueError("The STAC response limit must be between 10 KB and 8 MB.")
        self._endpoint = endpoint
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._maximum_response_bytes = maximum_response_bytes

    async def search(
        self, query: GroundImageryCatalogQuery
    ) -> GroundImageryCatalogPage:
        payload = {
            "collections": [_collection_for(query.sensor)],
            "intersects": query.geometry.as_geojson(),
            "datetime": f"{_utc_text(query.start)}/{_utc_text(query.end)}",
            "limit": query.limit,
        }
        try:
            response = await self._request(payload, query.cursor)
        except CatalogSearchError:
            raise
        except httpx.TimeoutException as error:
            raise CatalogSearchError(
                "The CDSE catalog request timed out.",
                reason_code="catalog_timeout",
                retryable=True,
            ) from error
        except httpx.HTTPError as error:
            raise CatalogSearchError(
                "The CDSE catalog request failed.",
                reason_code="catalog_network_error",
                retryable=True,
            ) from error

        try:
            document = response.json()
            features = document.get("features")
            if not isinstance(features, list):
                raise ValueError("features is not a list")
            observations = tuple(
                _observation_from_feature(feature, query.sensor) for feature in features
            )
        except (ValueError, TypeError, KeyError) as error:
            raise CatalogSearchError(
                "The CDSE catalog returned an unsupported STAC schema.",
                reason_code="catalog_schema_invalid",
                retryable=False,
            ) from error
        next_cursor = _next_cursor(document)
        context = document.get("context")
        matched = (
            context.get("matched")
            if isinstance(context, dict) and isinstance(context.get("matched"), int)
            else None
        )
        scan_complete = next_cursor is None and (
            matched is None or matched <= len(observations)
        )
        return GroundImageryCatalogPage(
            observations=observations,
            next_cursor=next_cursor,
            scanned_count=len(observations),
            scan_complete=scan_complete,
            source_revision=(
                str(context.get("returned", ""))
                if isinstance(context, dict) and context.get("returned") is not None
                else None
            ),
        )

    async def _request(
        self, payload: dict[str, object], cursor: str | None
    ) -> httpx.Response:
        for attempt in range(3):
            if cursor is None:
                response = await self._client.post(
                    self._endpoint,
                    json=payload,
                    headers={"Accept": "application/geo+json, application/json"},
                    follow_redirects=False,
                )
            else:
                _validate_endpoint(cursor)
                response = await self._client.get(
                    cursor,
                    headers={"Accept": "application/geo+json, application/json"},
                    follow_redirects=False,
                )
            if response.status_code >= 500 and attempt < 2:
                continue
            if response.status_code == 429:
                raise CatalogSearchError(
                    "The CDSE catalog rate limit deferred this search.",
                    reason_code="catalog_rate_limited",
                    retryable=True,
                )
            if response.status_code >= 400:
                raise CatalogSearchError(
                    "The CDSE catalog rejected this search.",
                    reason_code="catalog_http_error",
                    retryable=response.status_code >= 500,
                )
            content_length = response.headers.get("content-length")
            if (
                content_length
                and content_length.isdigit()
                and int(content_length) > self._maximum_response_bytes
            ):
                raise CatalogSearchError(
                    "The CDSE catalog response exceeded its configured size limit.",
                    reason_code="catalog_response_too_large",
                    retryable=False,
                )
            if len(response.content) > self._maximum_response_bytes:
                raise CatalogSearchError(
                    "The CDSE catalog response exceeded its configured size limit.",
                    reason_code="catalog_response_too_large",
                    retryable=False,
                )
            return response
        raise CatalogSearchError(
            "The CDSE catalog remained unavailable after bounded retries.",
            reason_code="catalog_unavailable",
            retryable=True,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _collection_for(sensor: Sensor) -> str:
    return "sentinel-1-grd" if sensor is Sensor.SENTINEL_1 else "sentinel-2-l2a"


def _observation_from_feature(feature: object, sensor: Sensor) -> Observation:
    if not isinstance(feature, dict):
        raise TypeError("A STAC feature must be an object.")
    product_id = feature.get("id")
    geometry = feature.get("geometry")
    properties = feature.get("properties", {})
    if (
        not isinstance(product_id, str)
        or not isinstance(geometry, dict)
        or not isinstance(properties, dict)
    ):
        raise ValueError("A STAC feature is missing identity, geometry, or properties.")
    start = _property_datetime(properties, "start_datetime", "datetime")
    end = _property_datetime(properties, "end_datetime", "datetime")
    if end < start:
        raise ValueError("A STAC feature has a reversed sensing interval.")
    item_geometry = polygon_from_geojson(geometry)
    links = feature.get("links", [])
    source_url = _link_href(links, "self")
    assets = feature.get("assets", {})
    asset_values = (
        tuple(
            (name, value.get("href"))
            for name, value in assets.items()
            if isinstance(name, str)
            and isinstance(value, dict)
            and isinstance(value.get("href"), str)
            and value["href"].startswith(("https://", "http://"))
        )
        if isinstance(assets, dict)
        else ()
    )
    datatake = _first_string(properties, "s1:datatake_id", "sat:datatake_id")
    acquisition_id = datatake or product_id
    polarizations = _string_tuple(properties.get("sar:polarizations"))
    return Observation(
        observation_id=f"cdse:{product_id}",
        sensor=sensor,
        identity=AcquisitionIdentity(
            product_id=product_id,
            provider="cdse",
            acquisition_id=acquisition_id,
            datatake_id=datatake,
            platform=_first_string(
                properties, "platform", "sat:platform_international_designator"
            ),
            processing_version=_first_string(
                properties, "processing:version", "s2:processing_baseline"
            ),
            revision=_first_string(properties, "version", "processing:version"),
            source_url=source_url,
        ),
        capture=CaptureInterval(start, end),
        footprint=item_geometry,
        readiness=ObservationReadiness.CATALOGUED,
        acquisition_group_id=datatake or product_id,
        mode=_first_string(properties, "sar:instrument_mode", "s1:instrument_mode"),
        relative_orbit=_integer(
            properties.get("sat:relative_orbit", properties.get("s1:relative_orbit"))
        ),
        orbit_direction=_first_string(
            properties, "sat:orbit_state", "s1:orbit_direction"
        ),
        polarizations=polarizations,
        cloud_cover_fraction=_cloud_fraction(
            properties.get("eo:cloud_cover", properties.get("s2:cloud_cover"))
        ),
        provider_published_at=_property_datetime_optional(properties, "published"),
        catalog_updated_at=_property_datetime_optional(properties, "updated"),
        assets=tuple((name, href) for name, href in asset_values if href is not None),
    )


def _property_datetime(properties: dict[str, object], *names: str) -> datetime:
    for name in names:
        value = properties.get(name)
        if isinstance(value, str):
            return _parse_datetime(value)
    raise ValueError("A STAC feature is missing sensing time.")


def _property_datetime_optional(
    properties: dict[str, object], name: str
) -> datetime | None:
    value = properties.get(name)
    return _parse_datetime(value) if isinstance(value, str) else None


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("STAC timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _link_href(links: object, relation: str) -> str | None:
    if not isinstance(links, list):
        return None
    for link in links:
        if (
            isinstance(link, dict)
            and link.get("rel") == relation
            and isinstance(link.get("href"), str)
        ):
            href = link.get("href")
            return href if isinstance(href, str) else None
    return None


def _next_cursor(document: object) -> str | None:
    if not isinstance(document, dict):
        return None
    cursor = _link_href(document.get("links"), "next")
    if cursor is None:
        return None
    _validate_endpoint(cursor)
    return cursor


def _first_string(properties: dict[str, object], *names: str) -> str | None:
    for name in names:
        value = properties.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(
            sorted(
                item.strip() for item in value if isinstance(item, str) and item.strip()
            )
        )
    return ()


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _cloud_fraction(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if 0 <= value <= 100:
        return float(value) / 100
    return None


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_endpoint(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _ALLOWED_HOST
        or parsed.username
        or parsed.password
    ):
        raise ValueError("CDSE catalog URLs must use the registered HTTPS authority.")
    if parsed.fragment:
        raise ValueError("CDSE catalog URLs must not contain fragments.")
