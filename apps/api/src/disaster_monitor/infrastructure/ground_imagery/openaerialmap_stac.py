"""Incident-bounded OpenAerialMap STAC search adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from disaster_monitor.domain.imagery.regions import (
    MultiPolygon,
    geometries_intersect,
    polygon_from_geojson,
)

_SEARCH_URL = "https://api.imagery.hotosm.org/stac/search"
_LINK_HOSTS = frozenset({"api.imagery.hotosm.org", "s3.amazonaws.com"})


@dataclass(frozen=True, slots=True)
class OpenAerialMapItem:
    item_id: str
    incident_id: str
    captured_at: datetime
    catalogued_at: datetime
    footprint: MultiPolygon
    license_name: str
    creator: str
    provider: str
    source_url: str
    visual_asset_url: str
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class OpenAerialMapSearchResult:
    items: tuple[OpenAerialMapItem, ...]
    availability_statement: str
    search_region_hash: str
    starts_at: datetime
    ends_at: datetime


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("OpenAerialMap STAC value must be an object.")
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("OpenAerialMap STAC value must be an array.")
    return value


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _time(value: object) -> datetime:
    text = _text(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    result = datetime.fromisoformat(text)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("OpenAerialMap timestamps must include a timezone.")
    return result


def _safe_url(value: object) -> str:
    url = _text(value)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _LINK_HOSTS:
        raise ValueError("OpenAerialMap link is outside approved HTTPS hosts.")
    return url


class OpenAerialMapStacCatalog:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15,
        max_response_bytes: int = 4_000_000,
        result_limit: int = 50,
    ) -> None:
        if not 1 <= result_limit <= 100:
            raise ValueError("OpenAerialMap result limit must be between 1 and 100.")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes
        self._result_limit = result_limit

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(
        self,
        *,
        incident_id: str,
        region: MultiPolygon,
        starts_at: datetime,
        ends_at: datetime,
        now: datetime,
    ) -> OpenAerialMapSearchResult:
        if starts_at >= ends_at:
            raise ValueError("OpenAerialMap search window must have positive duration.")
        body = {
            "collections": ["openaerialmap"],
            "bbox": list(region.bounds),
            "datetime": f"{starts_at.isoformat()}/{ends_at.isoformat()}",
            "limit": self._result_limit,
        }
        response = await self._client.post(
            _SEARCH_URL, json=body, follow_redirects=False
        )
        response.raise_for_status()
        if len(response.content) > self._max_response_bytes:
            raise ValueError("OpenAerialMap response exceeds the configured limit.")
        document = _mapping(response.json())
        items: list[OpenAerialMapItem] = []
        for raw in _list(document.get("features")):
            feature = _mapping(raw)
            footprint = polygon_from_geojson(_mapping(feature.get("geometry")))
            if not geometries_intersect(region, footprint):
                continue
            properties = _mapping(feature.get("properties"))
            providers = _list(properties.get("providers"))
            provider = (
                _text(_mapping(providers[0]).get("name"))
                if providers
                else "OpenAerialMap contributor"
            )
            links = [_mapping(item) for item in _list(feature.get("links"))]
            source_link = next(
                (item for item in links if _text(item.get("rel")) == "self"), None
            )
            assets = _mapping(feature.get("assets"))
            visual = _mapping(assets.get("visual"))
            items.append(
                OpenAerialMapItem(
                    item_id=_text(feature.get("id")),
                    incident_id=incident_id,
                    captured_at=_time(properties.get("datetime")),
                    catalogued_at=_time(properties.get("created")),
                    footprint=footprint,
                    license_name=_text(properties.get("license")),
                    creator=_text(properties.get("oam:creator")) or provider,
                    provider=provider,
                    source_url=_safe_url(source_link.get("href"))
                    if source_link
                    else "",
                    visual_asset_url=_safe_url(visual.get("href")),
                    retrieved_at=now,
                )
            )
        ordered = tuple(
            sorted(items, key=lambda item: (item.captured_at, item.item_id))
        )
        count = len(ordered)
        statement = (
            "No optional open aerial imagery found for this region and time window"
            if count == 0
            else f"{count} optional open aerial image{'s' if count != 1 else ''} found"
        )
        return OpenAerialMapSearchResult(
            ordered, statement, region.sha256(), starts_at, ends_at
        )
