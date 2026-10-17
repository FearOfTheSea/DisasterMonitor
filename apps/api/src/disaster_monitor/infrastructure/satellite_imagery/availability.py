"""Bounded WMTS temporal metadata; advertised times do not guarantee local tiles."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
from defusedxml import ElementTree

from disaster_monitor.application.ports.satellite_imagery import (
    SatelliteProductAvailability,
)
from disaster_monitor.infrastructure.disaster.errors import ProviderFailure
from disaster_monitor.infrastructure.disaster.http_backoff import (
    check_cooldown,
    record_failure,
)

CAPABILITIES_URL = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml"
)
LAYERS = {
    "nasa-viirs-snpp-true-color": "VIIRS_SNPP_CorrectedReflectance_TrueColor",
    "nasa-modis-terra-true-color": "MODIS_Terra_CorrectedReflectance_TrueColor",
    "nasa-modis-aqua-true-color": "MODIS_Aqua_CorrectedReflectance_TrueColor",
    "nasa-goes-east-geocolor": "GOES-East_ABI_GeoColor",
    "nasa-goes-west-geocolor": "GOES-West_ABI_GeoColor",
    "nasa-himawari-9-visible": "Himawari_AHI_Band3_Red_Visible_1km",
}
NS = {"w": "http://www.opengis.net/wmts/1.0", "o": "http://www.opengis.net/ows/1.1"}
LIMITS = (
    (
        "Advertised temporal availability does not guarantee imagery "
        "at the selected location. Polar sensors have swath and "
        "daylight gaps; geostationary sensors have regional "
        "footprints. Clouds can obscure visible imagery."
    ),
)


class GibsAvailability:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._client, self._clock = client, clock
        self._rows: tuple[SatelliteProductAvailability, ...] = ()
        self._checked: datetime | None = None
        self._task: asyncio.Task[tuple[SatelliteProductAvailability, ...]] | None = None

    async def availability(self) -> tuple[SatelliteProductAvailability, ...]:
        lifetime = (
            timedelta(minutes=15)
            if self._rows
            and all(row.state in ("available", "empty") for row in self._rows)
            else timedelta(minutes=1)
        )
        if self._checked and self._clock() - self._checked < lifetime:
            return self._rows
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._retrieve())
        return await asyncio.shield(self._task)

    async def _retrieve(self) -> tuple[SatelliteProductAvailability, ...]:
        now = self._clock()
        try:
            data = bytearray()
            check_cooldown(self._client, CAPABILITIES_URL)
            async with self._client.stream("GET", CAPABILITIES_URL) as response:
                if response.status_code == 429 or response.status_code >= 500:
                    record_failure(
                        self._client,
                        response,
                        ProviderFailure(
                            "http_error",
                            retryable=True,
                            http_status=response.status_code,
                        ),
                        final_attempt=True,
                    )
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 12_000_000:
                        raise ValueError(
                            "GIBS capabilities exceeds the metadata byte limit."
                        )
            root = ElementTree.fromstring(bytes(data))
            layers = {
                layer.findtext("o:Identifier", namespaces=NS): layer
                for layer in root.findall("w:Contents/w:Layer", NS)
            }
            rows = []
            for source_id, layer_id in LAYERS.items():
                layer = layers.get(layer_id)
                dimension = (
                    next(
                        (
                            item
                            for item in layer.findall("w:Dimension", NS)
                            if item.findtext("o:Identifier", namespaces=NS) == "Time"
                        ),
                        None,
                    )
                    if layer is not None
                    else None
                )
                default = (
                    dimension.findtext("w:Default", namespaces=NS)
                    if dimension is not None
                    else None
                )
                values = (
                    tuple(
                        item.text.strip()
                        for item in dimension.findall("w:Value", NS)
                        if item.text
                    )
                    if dimension is not None
                    else ()
                )
                if default:
                    try:
                        datetime.fromisoformat(default.replace("Z", "+00:00"))
                    except ValueError:
                        default = None
                available = bool(default and values)
                rows.append(
                    SatelliteProductAvailability(
                        source_id,
                        "available" if available else "empty",
                        default if available else None,
                        values[:5000],
                        now,
                        LIMITS
                        + (
                            ()
                            if available
                            else (
                                (
                                    "The provider advertises no usable "
                                    "default Time dimension for"
                                    " this layer."
                                ),
                            )
                        ),
                    )
                )
            self._rows = tuple(rows)
        except Exception:
            if self._rows and any(row.default_time for row in self._rows):
                self._rows = tuple(
                    replace(
                        row,
                        state="degraded",
                        limitations=row.limitations
                        + (
                            (
                                "Temporal metadata refresh failed; the last successful "
                                "metadata is retained."
                            ),
                        ),
                    )
                    for row in self._rows
                )
            else:
                self._rows = tuple(
                    SatelliteProductAvailability(
                        source_id,
                        "error",
                        None,
                        (),
                        None,
                        (
                            (
                                "GIBS temporal metadata could not be "
                                "retrieved or parsed. "
                                "Select an explicit date or retry later."
                            ),
                        ),
                    )
                    for source_id in LAYERS
                )
        self._checked = now
        return self._rows

    async def aclose(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
