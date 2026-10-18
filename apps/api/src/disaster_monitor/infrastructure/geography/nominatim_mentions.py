"""Opt-in, cached named-place lookup under the configured operator's policy.

The public endpoint is not enabled by default. One process serializes queries at
four per minute, persists results, honors Retry-After and caps new work per scan.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import httpx
from shapely.geometry import shape

from disaster_monitor.application.ports.mention_geography import PlaceResolution
from disaster_monitor.domain.events import (
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.news.request_schedule import ScheduledNewsJson


class NominatimMentionResolver:
    def __init__(
        self,
        endpoint: str,
        cache_path: Path,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Place resolver requires a configured HTTPS endpoint.")
        self._endpoint = endpoint
        self._path = cache_path
        self._client = client or httpx.AsyncClient(
            timeout=12,
            trust_env=False,
            headers={
                "User-Agent": "DisasterMonitor/1.0 source-place-inspection "
                "(local desktop)"
            },
        )
        self._owns_client = client is None
        self._lock = asyncio.Lock()
        self._schedule = ScheduledNewsJson(
            self._client, minimum_interval=15, timeout_seconds=30
        )
        self._retry_after = 0.0
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self._cache = payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            self._cache = {}

    async def resolve(self, place: str, country_context: str | None) -> PlaceResolution:
        query = ", ".join(dict.fromkeys(p for p in (place, country_context) if p))[:220]
        async with self._lock:
            payload = self._cache.get(query)
            if payload is None:
                if monotonic() < self._retry_after:
                    return PlaceResolution(
                        "unavailable",
                        detail="Place provider cooldown; source wording retained.",
                    )
                try:
                    snapshot = await self._schedule.get(
                        self._endpoint,
                        {
                            "q": query,
                            "format": "jsonv2",
                            "limit": "3",
                            "polygon_geojson": "1",
                            "polygon_threshold": "0.005",
                            "accept-language": "en",
                        },
                    )
                    payload = {
                        "items": snapshot.payload,
                        "retrieved_at": snapshot.retrieved_at.isoformat(),
                    }
                    self._cache[query] = payload
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self._path.with_suffix(".tmp")
                    temporary.write_text(
                        json.dumps(dict(list(self._cache.items())[-512:])),
                        encoding="utf-8",
                    )
                    temporary.replace(self._path)
                except Exception:
                    self._retry_after = monotonic() + 900
                    return PlaceResolution(
                        "unavailable",
                        detail="Place provider failed or restricted access; "
                        "source wording retained.",
                    )
            if not isinstance(payload, dict) or not isinstance(
                payload.get("items"), list
            ):
                return PlaceResolution(
                    "unavailable", detail="Invalid place-provider response."
                )
            items = payload["items"]
            if len(items) != 1:
                return PlaceResolution(
                    "ambiguous" if items else "unresolved",
                    detail="Multiple or no geographic matches; no location selected.",
                )
            item = items[0]
            if not isinstance(item, dict) or str(item.get("addresstype")) in {
                "country",
                "continent",
            }:
                return PlaceResolution(
                    "unresolved",
                    detail="Broad country/continent result cannot supply "
                    "an event point.",
                )
            geo = item.get("geojson")
            matched_name = (
                str(item.get("name") or item.get("display_name") or "")
                .split(",", 1)[0]
                .strip()
            )
            if matched_name.casefold() != place.casefold():
                return PlaceResolution(
                    "unresolved",
                    detail="Geographic result does not match the reported place "
                    "wording; no location selected.",
                )
            if not isinstance(geo, dict) or geo.get("type") != "Polygon":
                return PlaceResolution(
                    "unresolved",
                    detail="No supported administrative polygon; "
                    "point centroids are not event locations.",
                )
            try:
                polygon = shape(geo)
                if (
                    not polygon.is_valid
                    or polygon.is_empty
                    or polygon.geom_type != "Polygon"
                ):
                    raise ValueError("Invalid geographic polygon")
                coordinates = tuple(
                    EventCoordinate(y, x) for x, y in polygon.exterior.coords
                )
                if not 4 <= len(coordinates) <= 1000:
                    raise ValueError("Place boundary exceeds display budget")
                kind = {"relation": "relation", "way": "way", "node": "node"}.get(
                    str(item.get("osm_type"))
                )
                identifier = int(item["osm_id"])
                if not kind or identifier <= 0:
                    raise ValueError("Missing geographic identity")
                source = SourceReference(
                    "osm-nominatim",
                    "OpenStreetMap contributors (ODbL)",
                    str(item.get("display_name") or place),
                    f"https://www.openstreetmap.org/{kind}/{identifier}",
                    None,
                    None,
                    datetime.fromisoformat(payload["retrieved_at"]),
                    publication_precision="unknown",
                )
                geometry = EventGeometry(
                    EventGeometryKind.AREA,
                    source,
                    coordinates,
                    description=f"Administrative area for reported place '{place}'; "
                    "simplified OpenStreetMap boundary. Inspection context, "
                    "not a damage footprint.",
                    estimated=True,
                )
                return PlaceResolution(
                    "resolved",
                    geometry,
                    "Administrative area resolved by OpenStreetMap contributors "
                    "(ODbL); not an exact event site or damage footprint.",
                )
            except (ValueError, TypeError, KeyError):
                return PlaceResolution(
                    "unresolved",
                    detail="Geographic boundary validation failed; no geometry used.",
                )

    async def aclose(self) -> None:
        await self._schedule.aclose()
        if self._owns_client:
            await self._client.aclose()
