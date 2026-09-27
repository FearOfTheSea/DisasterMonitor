"""Authenticated Copernicus Data Space Process adapter.

The adapter is intentionally strict about source identity.  A successful HTTP
response without a source-product identity is not published as a verified
acquisition.
"""

from __future__ import annotations

import io
import json
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import cast
from urllib.parse import urlparse

import httpx
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from disaster_monitor.application.ports.ground_imagery.rendering import (
    GroundImageryRenderer,
    GroundImageryRenderError,
    RenderedRaster,
    RenderRequest,
)
from disaster_monitor.domain.imagery.observations import Observation, Sensor

DEFAULT_PROCESS_URL = "https://sh.dataspace.copernicus.eu/process/v1"
DEFAULT_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)
_PROCESS_HOST = "sh.dataspace.copernicus.eu"
_TOKEN_HOST = "identity.dataspace.copernicus.eu"
_ARCHIVE_TYPES = {"application/x-tar", "application/tar"}


class ProcessRenderingError(GroundImageryRenderError):
    """A Process request cannot produce a verified bounded raster."""


@dataclass(frozen=True, slots=True)
class _Token:
    value: str
    expires_at: float


class CopernicusDataSpaceProcessRenderer(GroundImageryRenderer):
    """Render an already-selected product through the CDSE Process API."""

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        process_url: str = DEFAULT_PROCESS_URL,
        token_url: str = DEFAULT_TOKEN_URL,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 180,
        maximum_response_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        _validate_authority(process_url, _PROCESS_HOST)
        _validate_authority(token_url, _TOKEN_HOST)
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._process_url = process_url.rstrip("/")
        self._token_url = token_url
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._maximum_response_bytes = maximum_response_bytes
        self._token: _Token | None = None

    @property
    def available(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def render(self, request: RenderRequest) -> RenderedRaster:
        if not self.available:
            raise ProcessRenderingError(
                "Copernicus Data Space processing credentials are not configured.",
                reason_code="credentials_required",
                retryable=False,
            )
        payload = build_process_request(request)
        for token_attempt in range(2):
            token = await self._access_token(force_refresh=token_attempt == 1)
            try:
                response = await self._client.post(
                    self._process_url,
                    json=payload,
                    headers={
                        "Accept": "application/x-tar",
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    follow_redirects=False,
                )
            except httpx.TimeoutException as error:
                raise ProcessRenderingError(
                    "The Copernicus Data Space processing request timed out.",
                    reason_code="processing_timeout",
                    retryable=True,
                ) from error
            except httpx.HTTPError as error:
                raise ProcessRenderingError(
                    "The Copernicus Data Space processing request failed.",
                    reason_code="processing_network_error",
                    retryable=True,
                ) from error
            if response.status_code == 401 and token_attempt == 0:
                continue
            if response.status_code == 429:
                raise ProcessRenderingError(
                    "The Copernicus Data Space processing quota deferred this request.",
                    reason_code="quota_deferred",
                    retryable=True,
                )
            if response.status_code in {401, 403}:
                raise ProcessRenderingError(
                    "Copernicus Data Space credentials cannot access processing.",
                    reason_code="permission_denied"
                    if response.status_code == 403
                    else "credentials_required",
                    retryable=False,
                )
            if response.status_code >= 500:
                raise ProcessRenderingError(
                    "Copernicus Data Space processing is temporarily unavailable.",
                    reason_code="processing_unavailable",
                    retryable=True,
                )
            if response.status_code >= 400:
                raise ProcessRenderingError(
                    "Copernicus Data Space rejected the bounded processing request.",
                    reason_code="processing_request_invalid",
                    retryable=False,
                )
            media_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if media_type not in _ARCHIVE_TYPES:
                raise ProcessRenderingError(
                    "Copernicus Data Space returned an unsupported artifact bundle.",
                    reason_code="unexpected_content_type",
                    retryable=False,
                )
            if len(response.content) > self._maximum_response_bytes:
                raise ProcessRenderingError(
                    "The processed raster exceeded its configured size limit.",
                    reason_code="response_too_large",
                    retryable=False,
                )
            raster_bytes, source_ids = _verified_response_raster(response, request)
            return RenderedRaster(
                content=raster_bytes,
                media_type="image/tiff",
                source_product_ids=source_ids,
                provider_metadata=(
                    ("source_identity", source_ids[0]),
                    ("process_endpoint", self._process_url),
                    ("sensor", request.observation.sensor.value),
                    (
                        "band_order",
                        "VV,VH,dataMask"
                        if request.observation.sensor is Sensor.SENTINEL_1
                        else "B04,B03,B02,SCL,dataMask",
                    ),
                ),
            )
        raise ProcessRenderingError(
            "Copernicus Data Space token renewal did not authorize processing.",
            reason_code="credentials_required",
            retryable=False,
        )

    async def _access_token(self, *, force_refresh: bool) -> str:
        if (
            not force_refresh
            and self._token is not None
            and self._token.expires_at > monotonic() + 30
        ):
            return self._token.value
        try:
            response = await self._client.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Accept": "application/json"},
                follow_redirects=False,
            )
        except httpx.HTTPError as error:
            raise ProcessRenderingError(
                "The CDSE token request failed.",
                reason_code="credentials_unavailable",
                retryable=True,
            ) from error
        if response.status_code >= 400:
            raise ProcessRenderingError(
                "The CDSE token endpoint rejected the configured credentials.",
                reason_code="credentials_required"
                if response.status_code in {401, 403}
                else "token_http_error",
                retryable=response.status_code >= 500,
            )
        try:
            document = response.json()
            value = document["access_token"]
            expires = int(document.get("expires_in", 300))
        except (ValueError, KeyError, TypeError) as error:
            raise ProcessRenderingError(
                "The CDSE token response has an unsupported schema.",
                reason_code="token_schema_invalid",
                retryable=False,
            ) from error
        if not isinstance(value, str) or not value.strip():
            raise ProcessRenderingError(
                "The CDSE token response did not contain a usable token.",
                reason_code="credentials_required",
                retryable=False,
            )
        self._token = _Token(value.strip(), monotonic() + max(1, expires))
        return self._token.value

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def build_process_request(request: RenderRequest) -> dict[str, object]:
    """Build a TILE-scoped request carrying exact selected-product identity."""
    observation = request.observation
    collection = (
        "sentinel-1-grd"
        if observation.sensor is Sensor.SENTINEL_1
        else "sentinel-2-l2a"
    )
    evalscript = (
        _sentinel_1_evalscript(observation, request.output_kind)
        if observation.sensor is Sensor.SENTINEL_1
        else _sentinel_2_evalscript(observation, request.output_kind)
    )
    return {
        "input": {
            "bounds": {
                "geometry": _project_region(request),
                "properties": {"crs": _crs_uri(request.grid.crs)},
            },
            "data": [
                {
                    "type": collection,
                    "dataFilter": {
                        "timeRange": {
                            "from": _utc_text(
                                observation.capture.start - timedelta(hours=1)
                            ),
                            "to": _utc_text(
                                observation.capture.end + timedelta(hours=1)
                            ),
                        },
                        "mosaickingOrder": (
                            "mostRecent"
                            if observation.sensor is Sensor.SENTINEL_1
                            else "leastCC"
                        ),
                    },
                    "processing": {
                        "orthorectify": observation.sensor is Sensor.SENTINEL_1,
                        **(
                            {"backCoeff": "GAMMA0_TERRAIN"}
                            if observation.sensor is Sensor.SENTINEL_1
                            else {}
                        ),
                    },
                }
            ],
        },
        "output": {
            "width": request.grid.width,
            "height": request.grid.height,
            "responses": [
                {
                    "identifier": "default",
                    "format": {"type": "image/tiff"},
                },
                {"identifier": "userdata", "format": {"type": "application/json"}},
            ],
        },
        "evalscript": evalscript,
    }


def _sentinel_2_evalscript(observation: Observation, output_kind: str) -> str:
    del output_kind
    script = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ['B04', 'B03', 'B02', 'SCL', 'dataMask'] }],
    mosaicking: Mosaicking.TILE,
    output: { bands: 5, sampleType: 'FLOAT32' }
  };
}
function evaluatePixel(samples) {
  const sample = samples.find(item => item.dataMask === 1) || samples[0];
  if (!sample) return [0, 0, 0, 0, 0];
  return [sample.B04, sample.B03, sample.B02, sample.SCL, sample.dataMask];
}"""
    return script + _source_scene_script(observation.identity.product_id)


def _sentinel_1_evalscript(observation: Observation, output_kind: str) -> str:
    del output_kind
    script = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ['VV', 'VH', 'dataMask'] }],
    mosaicking: Mosaicking.TILE,
    output: { bands: 3, sampleType: 'FLOAT32' }
  };
}
function evaluatePixel(samples) {
  const sample = samples.find(item => item.dataMask === 1) || samples[0];
  if (!sample) return [0, 0, 0];
  return [sample.VV, sample.VH, sample.dataMask];
}"""
    return script + _source_scene_script(observation.identity.product_id)


def _source_scene_script(product_id: str) -> str:
    product_literal = json.dumps(product_id + ".SAFE")
    return f"""
function sourceId(tile) {{
  return tile.productId || tile.sentinel1ProductId || tile.sentinel2ProductId;
}}
function preProcessScenes(collections) {{
  collections.scenes.tiles = collections.scenes.tiles.filter(
    tile => sourceId(tile) === {product_literal}
  );
  return collections;
}}
function updateOutputMetadata(scenes, inputMetadata, outputMetadata) {{
  outputMetadata.userData = {{
    productIds: scenes.tiles.map(sourceId).filter(Boolean)
  }};
}}"""


def _project_region(request: RenderRequest) -> dict[str, object]:
    source = shape(request.region.as_geojson())
    transformer = Transformer.from_crs(
        "EPSG:4326", CRS.from_user_input(request.grid.crs), always_xy=True
    )
    return cast(dict[str, object], mapping(transform(transformer.transform, source)))


def _crs_uri(value: str) -> str:
    crs = CRS.from_user_input(value)
    epsg = crs.to_epsg()
    if epsg is None:
        raise ProcessRenderingError(
            "The selected imagery grid has no EPSG authority for Process API bounds.",
            reason_code="grid_crs_unsupported",
            retryable=False,
        )
    return f"http://www.opengis.net/def/crs/EPSG/0/{epsg}"


def _verified_response_raster(
    response: httpx.Response, request: RenderRequest
) -> tuple[bytes, tuple[str, ...]]:
    try:
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:") as archive:
            if set(archive.getnames()) != {"default.tif", "userdata.json"}:
                raise ValueError("Unexpected Process bundle members.")
            image = archive.extractfile("default.tif")
            metadata = archive.extractfile("userdata.json")
            if image is None or metadata is None:
                raise ValueError("Missing Process bundle data.")
            raster_bytes = image.read()
            if not raster_bytes or len(raster_bytes) > 128 * 1024 * 1024:
                raise ValueError("Process raster size is invalid.")
            if archive.getmember("userdata.json").size > 1_000_000:
                raise ValueError("Process metadata exceeds its bound.")
            document = json.load(metadata)
            source_ids = document.get("productIds")
            if not isinstance(source_ids, list) or not all(
                isinstance(value, str) for value in source_ids
            ):
                raise ValueError("Process source identity is missing.")
    except (tarfile.TarError, OSError, ValueError, TypeError) as error:
        raise ProcessRenderingError(
            "Copernicus Data Space returned an invalid artifact bundle.",
            reason_code="processing_response_invalid",
            retryable=False,
        ) from error
    normalized = tuple(
        dict.fromkeys(
            value[:-5] if value.endswith(".SAFE") else value for value in source_ids
        )
    )
    if normalized != (request.observation.identity.product_id,):
        raise ProcessRenderingError(
            "Copernicus Data Space did not prove the selected source-product identity.",
            reason_code="source_identity_unverified",
            retryable=False,
        )
    return raster_bytes, normalized


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_authority(value: str, host: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "CDSE processing URLs must use their registered HTTPS authorities."
        )
