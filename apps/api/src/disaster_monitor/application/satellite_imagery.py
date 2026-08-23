"""Validated satellite-imagery catalog and tile retrieval use case."""

import re
from datetime import date, datetime

from disaster_monitor.application.ports.satellite_imagery import (
    SatelliteImageryProduct,
    SatelliteImageryProvider,
    SatelliteRasterTile,
    SatelliteTileRequest,
)

_DAILY_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SUBDAILY_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z$")


class SatelliteImageryError(Exception):
    """Base class for presentation-safe imagery failures."""


class SatelliteImageryInputError(SatelliteImageryError):
    """A request escaped the configured product or tile bounds."""


class SatelliteImageryUnavailableError(SatelliteImageryError):
    """A known provider is not configured on this server."""


class SatelliteImageryUpstreamError(SatelliteImageryError):
    """A fixed upstream failed a bounded raster request."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class SatelliteImageryService:
    """Expose a safe catalog and dispatch protected tiles to fixed providers."""

    def __init__(self, providers: tuple[SatelliteImageryProvider, ...]) -> None:
        self._providers = providers
        self._providers_by_id: dict[str, SatelliteImageryProvider] = {}
        self._products: tuple[SatelliteImageryProduct, ...] = tuple(
            product for provider in providers for product in provider.products
        )
        self._products_by_id: dict[str, SatelliteImageryProduct] = {}
        for provider in providers:
            if provider.provider_id in self._providers_by_id:
                raise ValueError("Satellite imagery provider IDs must be unique.")
            self._providers_by_id[provider.provider_id] = provider
            for product in provider.products:
                if product.provider_id != provider.provider_id:
                    raise ValueError(
                        "Satellite imagery products must match their provider."
                    )
                if product.source_id in self._products_by_id:
                    raise ValueError("Satellite imagery source IDs must be unique.")
                self._products_by_id[product.source_id] = product

    def catalog(self) -> tuple[SatelliteImageryProduct, ...]:
        return self._products

    async def fetch_tile(self, request: SatelliteTileRequest) -> SatelliteRasterTile:
        provider = self._providers_by_id.get(request.provider_id)
        product = self._products_by_id.get(request.source_id)
        if (
            provider is None
            or product is None
            or product.provider_id != request.provider_id
        ):
            raise SatelliteImageryInputError(
                "The satellite imagery provider or product is not supported."
            )
        if product.access_mode != "api":
            raise SatelliteImageryInputError(
                "This satellite imagery source is served directly by its public "
                "service."
            )
        if not product.available:
            raise SatelliteImageryUnavailableError(
                "The satellite imagery provider is not configured on this server."
            )
        _validate_tile_coordinates(request, product.maximum_useful_zoom)
        _validate_observation_time(request.observation_time, product)
        return await provider.fetch_tile(request)

    async def aclose(self) -> None:
        for provider in self._providers:
            await provider.aclose()


def _validate_tile_coordinates(
    request: SatelliteTileRequest, maximum_useful_zoom: int
) -> None:
    if request.z < 0 or request.z > maximum_useful_zoom:
        raise SatelliteImageryInputError(
            "The satellite tile zoom is outside its bounds."
        )
    width = 1 << request.z
    if request.x < 0 or request.x >= width or request.y < 0 or request.y >= width:
        raise SatelliteImageryInputError(
            "The satellite tile coordinate is outside its zoom grid."
        )


def _validate_observation_time(
    value: str | None, product: SatelliteImageryProduct
) -> None:
    if product.temporal_mode == "fixed":
        if value is not None:
            raise SatelliteImageryInputError(
                "The configured mosaic does not accept an observation time."
            )
        return
    if value is None:
        raise SatelliteImageryInputError("An observation time is required.")
    if product.temporal_mode == "daily":
        if not _DAILY_TIME.fullmatch(value):
            raise SatelliteImageryInputError("A valid daily date is required.")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise SatelliteImageryInputError(
                "A valid daily date is required."
            ) from error
        return
    if not _SUBDAILY_TIME.fullmatch(value):
        raise SatelliteImageryInputError(
            "A valid UTC observation date/time is required."
        )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise SatelliteImageryInputError(
            "A valid UTC observation date/time is required."
        ) from error
    step = product.temporal_step_minutes or 1
    if parsed.minute % step != 0:
        raise SatelliteImageryInputError(
            f"The observation time must use {step}-minute increments."
        )
