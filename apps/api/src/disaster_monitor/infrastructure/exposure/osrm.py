"""Bounded route visualization over an operator-controlled OSRM instance."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import httpx

from disaster_monitor.domain.exposure import AccessRouteEstimate, RouteProfile
from disaster_monitor.domain.imagery.regions import Coordinate

_OSRM_PROFILES = {
    RouteProfile.DRIVING: "driving",
    RouteProfile.CYCLING: "cycling",
    RouteProfile.WALKING: "walking",
}


class SelfHostedOsrmAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        data_version: str,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        maximum_response_bytes: int = 2_000_000,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not _local_host(parsed.hostname):
            raise ValueError("OSRM routing must use a self-hosted local/private host.")
        if not data_version.strip():
            raise ValueError("OSRM routing requires an OSM data version.")
        self._base_url = base_url.rstrip("/")
        self._data_version = data_version
        self._client = client or httpx.AsyncClient(timeout=10)
        self._owns_client = client is None
        self._clock = clock
        self._maximum_response_bytes = maximum_response_bytes

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def route(
        self,
        origin: Coordinate,
        destination: Coordinate,
        profile: RouteProfile,
    ) -> AccessRouteEstimate:
        coordinates = (
            f"{origin.longitude},{origin.latitude};"
            f"{destination.longitude},{destination.latitude}"
        )
        response = await self._client.get(
            f"{self._base_url}/route/v1/{_OSRM_PROFILES[profile]}/{coordinates}",
            params={
                "alternatives": "false",
                "steps": "false",
                "overview": "full",
                "geometries": "geojson",
            },
            follow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > self._maximum_response_bytes:
            raise ValueError("OSRM route response exceeds the byte limit.")
        payload = response.json()
        route = _first_route(payload)
        path = _path(route)
        if not path:
            raise ValueError("OSRM route response has no valid path.")
        path = (origin, *path[1:-1], destination)
        identity = sha256(
            f"{coordinates}|{profile.value}|{self._data_version}".encode()
        ).hexdigest()[:24]
        return AccessRouteEstimate(
            route_id=f"route:{identity}",
            origin=origin,
            destination=destination,
            profile=profile,
            path=path,
            distance_m=float(route["distance"]),
            duration_seconds=float(route["duration"]),
            provider="self-hosted-osrm",
            data_version=self._data_version,
            calculated_at=self._clock(),
            limitation=(
                "Estimated access visualization only; not an evacuation route or "
                "safety guarantee. Road conditions may differ from the OSM extract."
            ),
        )


def _local_host(hostname: str | None) -> bool:
    if hostname in {"localhost", "host.docker.internal"}:
        return True
    try:
        return bool(hostname and ipaddress.ip_address(hostname).is_private)
    except ValueError:
        return bool(hostname and hostname.endswith((".local", ".internal")))


def _first_route(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("code") != "Ok":
        raise ValueError("OSRM did not return a usable route.")
    routes = payload.get("routes")
    if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
        raise ValueError("OSRM route list is missing.")
    return routes[0]


def _path(route: dict[str, Any]) -> tuple[Coordinate, ...]:
    geometry = route.get("geometry")
    coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if not isinstance(coordinates, list):
        return ()
    try:
        return tuple(
            Coordinate(latitude=float(item[1]), longitude=float(item[0]))
            for item in coordinates
        )
    except (IndexError, TypeError, ValueError):
        return ()
