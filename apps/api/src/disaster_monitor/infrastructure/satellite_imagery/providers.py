"""NASA catalog and credential-protected raster tile providers."""

from __future__ import annotations

from collections.abc import Mapping
from math import pi
from typing import Literal, cast
from urllib.parse import quote

import httpx

from disaster_monitor.application.ports.satellite_imagery import (
    SatelliteImageryProduct,
    SatelliteRasterTile,
    SatelliteTemporalMode,
    SatelliteTileRequest,
)
from disaster_monitor.application.satellite_imagery import (
    SatelliteImageryInputError,
    SatelliteImageryUnavailableError,
    SatelliteImageryUpstreamError,
)

_GIBS_ATTRIBUTION = (
    "We acknowledge the use of imagery provided by services from NASA's Global "
    "Imagery Browse Services (GIBS), part of NASA's Earth Science Data and "
    "Information System (ESDIS)."
)
_WEB_MERCATOR_HALF_WORLD = 6_378_137 * pi
_ACCEPTED_IMAGE_TYPES = {"image/jpeg", "image/png"}


class NasaGibsImageryProvider:
    """Credential-free catalog entries loaded directly by the browser from GIBS."""

    provider_id = "nasa-gibs"

    @property
    def products(self) -> tuple[SatelliteImageryProduct, ...]:
        return (
            self._product(
                source_id="nasa-viirs-snpp-true-color",
                display_name="NASA VIIRS Suomi-NPP True Color",
                temporal_mode="daily",
                maximum_useful_zoom=9,
            ),
            self._product(
                source_id="nasa-modis-terra-true-color",
                display_name="NASA MODIS Terra True Color",
                temporal_mode="daily",
                maximum_useful_zoom=9,
            ),
            self._product(
                source_id="nasa-modis-aqua-true-color",
                display_name="NASA MODIS Aqua True Color",
                temporal_mode="daily",
                maximum_useful_zoom=9,
            ),
            self._product(
                source_id="nasa-goes-east-geocolor",
                display_name="NASA GOES-East GeoColor",
                temporal_mode="subdaily",
                temporal_step_minutes=10,
                maximum_useful_zoom=7,
            ),
            self._product(
                source_id="nasa-goes-west-geocolor",
                display_name="NASA GOES-West GeoColor",
                temporal_mode="subdaily",
                temporal_step_minutes=10,
                maximum_useful_zoom=7,
            ),
            self._product(
                source_id="nasa-himawari-9-visible",
                display_name="NASA Himawari-9 visible imagery",
                temporal_mode="subdaily",
                temporal_step_minutes=10,
                maximum_useful_zoom=7,
            ),
        )

    def _product(
        self,
        *,
        source_id: str,
        display_name: str,
        temporal_mode: SatelliteTemporalMode,
        maximum_useful_zoom: int,
        temporal_step_minutes: int | None = None,
    ) -> SatelliteImageryProduct:
        return SatelliteImageryProduct(
            source_id=source_id,
            display_name=display_name,
            provider_id=self.provider_id,
            provider_name="NASA GIBS",
            temporal_mode=temporal_mode,
            temporal_step_minutes=temporal_step_minutes,
            attribution=_GIBS_ATTRIBUTION,
            maximum_useful_zoom=maximum_useful_zoom,
            access_mode="direct_gibs",
            available=True,
        )

    async def fetch_tile(self, request: SatelliteTileRequest) -> SatelliteRasterTile:
        raise SatelliteImageryInputError("NASA GIBS tiles are loaded directly.")

    async def aclose(self) -> None:
        return None


class _BoundedRasterProvider:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None,
        timeout_seconds: float,
        maximum_response_bytes: int,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._maximum_response_bytes = maximum_response_bytes

    async def _get_image(
        self,
        url: str,
        *,
        parameters: Mapping[str, str],
    ) -> SatelliteRasterTile:
        for attempt in range(2):
            try:
                async with self._client.stream(
                    "GET",
                    url,
                    params=parameters,
                    headers={"Accept": "image/png, image/jpeg"},
                    follow_redirects=False,
                ) as response:
                    if response.status_code >= 400:
                        if response.status_code >= 500 and attempt == 0:
                            continue
                        raise SatelliteImageryUpstreamError(
                            "The imagery provider returned an HTTP error.",
                            reason_code="http_error",
                        )
                    media_type = (
                        response.headers.get("content-type", "")
                        .partition(";")[0]
                        .strip()
                        .casefold()
                    )
                    if media_type not in _ACCEPTED_IMAGE_TYPES:
                        raise SatelliteImageryUpstreamError(
                            "The imagery provider returned a non-raster response.",
                            reason_code="unexpected_content_type",
                        )
                    declared_length = response.headers.get("content-length")
                    if (
                        declared_length is not None
                        and declared_length.isdigit()
                        and int(declared_length) > self._maximum_response_bytes
                    ):
                        raise SatelliteImageryUpstreamError(
                            "The imagery response exceeded its configured size limit.",
                            reason_code="response_too_large",
                        )
                    content = bytearray()
                    async for chunk in response.aiter_bytes(
                        chunk_size=min(64 * 1024, self._maximum_response_bytes + 1)
                    ):
                        remaining = self._maximum_response_bytes + 1 - len(content)
                        content.extend(chunk[:remaining])
                        if len(content) > self._maximum_response_bytes:
                            raise SatelliteImageryUpstreamError(
                                "The imagery response exceeded its configured size "
                                "limit.",
                                reason_code="response_too_large",
                            )
                    if not content:
                        raise SatelliteImageryUpstreamError(
                            "The imagery provider returned an empty response.",
                            reason_code="empty_response",
                        )
                    return SatelliteRasterTile(
                        bytes(content),
                        cast(Literal["image/jpeg", "image/png"], media_type),
                    )
            except SatelliteImageryUpstreamError:
                raise
            except httpx.TimeoutException as error:
                if attempt == 0:
                    continue
                raise SatelliteImageryUpstreamError(
                    "The imagery provider request timed out.", reason_code="timeout"
                ) from error
            except httpx.HTTPError as error:
                if attempt == 0:
                    continue
                raise SatelliteImageryUpstreamError(
                    "The imagery provider network request failed.",
                    reason_code="network_error",
                ) from error
        raise AssertionError("The bounded imagery request did not terminate.")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class SentinelHubImageryProvider(_BoundedRasterProvider):
    """Proxy a configured Sentinel Hub WMS layer without exposing its instance ID."""

    provider_id = "copernicus-sentinel-hub"

    def __init__(
        self,
        *,
        instance_id: str | None,
        layer_id: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
        maximum_response_bytes: int = 1_000_000,
    ) -> None:
        super().__init__(
            client=client,
            timeout_seconds=timeout_seconds,
            maximum_response_bytes=maximum_response_bytes,
        )
        self._instance_id = (instance_id or "").strip()
        self._layer_id = layer_id.strip()

    @property
    def products(self) -> tuple[SatelliteImageryProduct, ...]:
        return (
            SatelliteImageryProduct(
                source_id="copernicus-sentinel-2-true-color",
                display_name="Copernicus Sentinel-2 True Color",
                provider_id=self.provider_id,
                provider_name="Copernicus Data Space / Sentinel Hub",
                temporal_mode="daily",
                attribution=(
                    "Contains modified Copernicus Sentinel data; served through "
                    "the configured Sentinel Hub service"
                ),
                maximum_useful_zoom=14,
                access_mode="api",
                available=bool(self._instance_id and self._layer_id),
            ),
        )

    async def fetch_tile(self, request: SatelliteTileRequest) -> SatelliteRasterTile:
        if not self._instance_id or not self._layer_id:
            raise SatelliteImageryUnavailableError(
                "The Copernicus Sentinel Hub provider is not configured."
            )
        if request.observation_time is None:
            raise SatelliteImageryInputError(
                "A Sentinel-2 observation date is required."
            )
        bbox = _xyz_web_mercator_bbox(request.z, request.x, request.y)
        return await self._get_image(
            "https://services.sentinel-hub.com/ogc/wms/"
            + quote(self._instance_id, safe=""),
            parameters={
                "BBOX": ",".join(f"{coordinate:.6f}" for coordinate in bbox),
                "CRS": "EPSG:3857",
                "FORMAT": "image/png",
                "HEIGHT": "256",
                "LAYERS": self._layer_id,
                "REQUEST": "GetMap",
                "SERVICE": "WMS",
                "STYLES": "",
                "TIME": (
                    f"{request.observation_time}T00:00:00Z/"
                    f"{request.observation_time}T23:59:59Z"
                ),
                "TRANSPARENT": "TRUE",
                "VERSION": "1.3.0",
                "WIDTH": "256",
            },
        )


class PlanetImageryProvider(_BoundedRasterProvider):
    """Proxy one server-configured Planet mosaic through its fixed XYZ endpoint."""

    provider_id = "planet"

    def __init__(
        self,
        *,
        api_key: str | None,
        mosaic_name: str | None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
        maximum_response_bytes: int = 1_000_000,
    ) -> None:
        super().__init__(
            client=client,
            timeout_seconds=timeout_seconds,
            maximum_response_bytes=maximum_response_bytes,
        )
        self._api_key = (api_key or "").strip()
        self._mosaic_name = (mosaic_name or "").strip()

    @property
    def products(self) -> tuple[SatelliteImageryProduct, ...]:
        return (
            SatelliteImageryProduct(
                source_id="planet-configured-mosaic",
                display_name="Planet configured mosaic",
                provider_id=self.provider_id,
                provider_name="Planet",
                temporal_mode="fixed",
                attribution="© Planet Labs PBC; configured mosaic",
                maximum_useful_zoom=18,
                access_mode="api",
                available=bool(self._api_key and self._mosaic_name),
            ),
        )

    async def fetch_tile(self, request: SatelliteTileRequest) -> SatelliteRasterTile:
        if not self._api_key or not self._mosaic_name:
            raise SatelliteImageryUnavailableError(
                "The Planet mosaic provider is not configured."
            )
        mosaic = quote(self._mosaic_name, safe="")
        return await self._get_image(
            "https://tiles.planet.com/basemaps/v1/planet-tiles/"
            f"{mosaic}/gmap/{request.z}/{request.x}/{request.y}.png",
            parameters={"api_key": self._api_key},
        )


def _xyz_web_mercator_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    tile_span = (2 * _WEB_MERCATOR_HALF_WORLD) / (1 << z)
    minimum_x = -_WEB_MERCATOR_HALF_WORLD + x * tile_span
    maximum_y = _WEB_MERCATOR_HALF_WORLD - y * tile_span
    return minimum_x, maximum_y - tile_span, minimum_x + tile_span, maximum_y
