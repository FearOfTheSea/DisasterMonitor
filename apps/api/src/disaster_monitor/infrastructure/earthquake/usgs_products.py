"""Bounded USGS detail-product adapter with explicit product lineage."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from disaster_monitor.application.ports.earthquake_context import (
    EarthquakeContextProviderError,
)
from disaster_monitor.domain.earthquake_context import (
    AftershockForecast,
    AftershockProbability,
    AftershockWindow,
    EarthquakeContext,
    GroundFailureKind,
    GroundFailureLayer,
    IntensityExposure,
    PagerImpact,
    ProbabilityBin,
    ProductBounds,
    ProductReference,
    ShakeMapLayer,
    ShakeMeasure,
)

_DETAIL_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/{event}.geojson"
_ALLOWED_HOST = "earthquake.usgs.gov"


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("USGS product data must be an object.")
    return value


def _sequence(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("USGS product data must be an array.")
    return value


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("A numeric USGS value is invalid.")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError("A numeric USGS value is invalid.") from error
    return result


def _integer(value: object) -> int:
    return int(_number(value))


def _timestamp(value: object) -> datetime:
    return datetime.fromtimestamp(_number(value) / 1000, tz=UTC)


def _content(product: Mapping[str, Any], suffix: str) -> Mapping[str, Any]:
    contents = _mapping(product.get("contents"))
    matches = [
        _mapping(value)
        for key, value in contents.items()
        if str(key).casefold().endswith(suffix.casefold())
    ]
    if not matches:
        raise ValueError(f"USGS product content {suffix!r} is missing.")
    return matches[0]


def _safe_url(content: Mapping[str, Any]) -> str:
    url = _text(content.get("url"))
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _ALLOWED_HOST:
        raise ValueError("USGS linked product URL is outside the approved host.")
    return url


def _event_id(properties: Mapping[str, Any]) -> str:
    source = _text(properties.get("eventsource"))
    code = _text(properties.get("eventsourcecode"))
    if not source or not code:
        raise ValueError("USGS product event identity is missing.")
    return f"{source}{code}"


def _product_reference(
    product: Mapping[str, Any], *, expected_event: str
) -> ProductReference:
    properties = _mapping(product.get("properties"))
    product_event = _event_id(properties)
    if product_event != expected_event:
        raise ValueError("USGS product event identity differs from the selected event.")
    product_id = _text(product.get("id"))
    release = _text(properties.get("release"))
    if release.casefold() in {"true", "false"}:
        release = ""
    version = (
        _text(properties.get("version"))
        or release
        or product_id.rsplit(":", maxsplit=1)[-1]
    )
    return ProductReference(
        product_id=product_id,
        product_type=_text(product.get("type")),
        version=version,
        status=_text(product.get("status")),
        updated_at=_timestamp(product.get("updateTime")),
        event_id=f"usgs:{expected_event}",
    )


def _bounds(properties: Mapping[str, Any], prefix: str = "") -> ProductBounds:
    return ProductBounds(
        min_latitude=_number(properties.get(f"{prefix}minimum-latitude")),
        min_longitude=_number(properties.get(f"{prefix}minimum-longitude")),
        max_latitude=_number(properties.get(f"{prefix}maximum-latitude")),
        max_longitude=_number(properties.get(f"{prefix}maximum-longitude")),
    )


def _latest(products: object) -> Mapping[str, Any] | None:
    values = _sequence(products)
    if not values:
        return None
    return max(
        (_mapping(value) for value in values),
        key=lambda item: _number(item.get("updateTime")),
    )


class UsgsEarthquakeProductsAdapter:
    """Retrieve event-scoped ShakeMap, PAGER, ground-failure, and OAF data."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _json(self, url: str) -> Mapping[str, Any]:
        try:
            response = await self._client.get(url, follow_redirects=False)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise EarthquakeContextProviderError(
                "The USGS event-product request failed."
            ) from error
        if len(response.content) > self._max_response_bytes:
            raise ValueError("USGS product response exceeds the configured limit.")
        if "json" not in response.headers.get("content-type", "").casefold():
            raise ValueError("USGS product response is not JSON.")
        return _mapping(response.json())

    async def fetch(self, event_id: str, *, now: datetime) -> EarthquakeContext:
        if (
            not event_id.startswith("usgs:")
            or not event_id.removeprefix("usgs:").isalnum()
        ):
            raise ValueError("A canonical USGS event identifier is required.")
        event = event_id.removeprefix("usgs:")
        document = await self._json(_DETAIL_URL.format(event=event))
        if _text(document.get("id")) != event:
            raise ValueError("USGS detail event identity differs from the request.")
        products = _mapping(_mapping(document.get("properties")).get("products"))
        shakemap = _latest(products.get("shakemap", []))
        pager = _latest(products.get("losspager", []))
        ground_failure = _latest(products.get("ground-failure", []))
        oaf = _latest(products.get("oaf", []))
        return EarthquakeContext(
            event_id=event_id,
            shakemap_layers=self._parse_shakemap(shakemap, event) if shakemap else (),
            pager=await self._parse_pager(pager, event) if pager else None,
            ground_failure=(
                self._parse_ground_failure(ground_failure, event)
                if ground_failure
                else ()
            ),
            aftershock_forecast=(await self._parse_oaf(oaf, event) if oaf else None),
            retrieved_at=now,
        )

    def _parse_shakemap(
        self, product: Mapping[str, Any], event: str
    ) -> tuple[ShakeMapLayer, ...]:
        reference = _product_reference(product, expected_event=event)
        properties = _mapping(product.get("properties"))
        overlay = _content(product, "intensity_overlay.png")
        legend = _content(product, "mmi_legend.png")
        definitions = (
            (ShakeMeasure.MMI, "MMI", "coverage_mmi_high_res.covjson", "maxmmi"),
            (ShakeMeasure.PGA, "%g", "coverage_pga_high_res.covjson", "maxpga"),
            (ShakeMeasure.PGV, "cm/s", "coverage_pgv_high_res.covjson", "maxpgv"),
        )
        layers: list[ShakeMapLayer] = []
        for measure, unit, suffix, maximum_key in definitions:
            coverage = _content(product, suffix)
            layers.append(
                ShakeMapLayer(
                    product=reference,
                    measure=measure,
                    unit=unit,
                    coverage_url=_safe_url(coverage),
                    coverage_sha256=_text(coverage.get("sha256")) or None,
                    bounds=_bounds(properties),
                    maximum=_number(properties[maximum_key])
                    if maximum_key in properties
                    else None,
                    overlay_url=_safe_url(overlay),
                    legend_url=_safe_url(legend),
                )
            )
        return tuple(layers)

    async def _parse_pager(self, product: Mapping[str, Any], event: str) -> PagerImpact:
        reference = _product_reference(product, expected_event=event)
        properties = _mapping(product.get("properties"))
        exposures = await self._json(_safe_url(_content(product, "exposures.json")))
        alerts = await self._json(_safe_url(_content(product, "alerts.json")))
        population = _mapping(exposures.get("population_exposure"))
        intensities = _sequence(population.get("mmi"))
        values = _sequence(population.get("aggregated_exposure"))
        economic = _mapping(exposures.get("economic_exposure"))
        economic_values = _sequence(economic.get("aggregated_exposure"))
        exposure_rows = tuple(
            IntensityExposure(
                intensity=_number(intensity),
                population=_integer(values[index]),
                economic_exposure_usd=(
                    _number(economic_values[index])
                    if index < len(economic_values)
                    else None
                ),
            )
            for index, intensity in enumerate(intensities)
            if index < len(values)
        )
        return PagerImpact(
            product=reference,
            alert_level=_text(properties.get("alertlevel")),
            exposure_by_intensity=exposure_rows,
            fatality_probability_bins=self._probability_bins(alerts, "fatality"),
            economic_loss_probability_bins=self._probability_bins(alerts, "economic"),
            interpretation=(
                "PAGER is a modelled impact estimate with probability ranges; it is "
                "not a confirmed fatality or loss count."
            ),
        )

    @staticmethod
    def _probability_bins(
        alerts: Mapping[str, Any], name: str
    ) -> tuple[ProbabilityBin, ...]:
        group = _mapping(alerts.get(name))
        unit = _text(group.get("units"))
        return tuple(
            ProbabilityBin(
                minimum=_number(item.get("min")),
                maximum=_number(item.get("max")),
                probability=_number(item.get("probability")),
                unit=unit,
            )
            for item in (_mapping(raw) for raw in _sequence(group.get("bins")))
        )

    def _parse_ground_failure(
        self, product: Mapping[str, Any], event: str
    ) -> tuple[GroundFailureLayer, ...]:
        reference = _product_reference(product, expected_event=event)
        properties = _mapping(product.get("properties"))
        definitions = (
            (GroundFailureKind.LANDSLIDE, "jessee_2018_model.tif"),
            (GroundFailureKind.LIQUEFACTION, "zhu_2017_general_model.tif"),
        )
        return tuple(
            GroundFailureLayer(
                product=reference,
                shakemap_version=_text(properties.get("shakemap-version")),
                kind=kind,
                alert_level=_text(properties.get(f"{kind.value}-alert")),
                hazard_value=_number(
                    properties.get(f"{kind.value}-hazard-alert-value")
                ),
                population_exposed=_integer(
                    properties.get(f"{kind.value}-population-alert-value")
                ),
                bounds=_bounds(properties, f"{kind.value}-"),
                raster_url=_safe_url(raster := _content(product, suffix)),
                raster_sha256=_text(raster.get("sha256")) or None,
                interpretation=(
                    f"USGS modelled {kind.value} susceptibility; values are estimates, "
                    "not confirmed ground-failure observations."
                ),
            )
            for kind, suffix in definitions
        )

    async def _parse_oaf(
        self, product: Mapping[str, Any], event: str
    ) -> AftershockForecast:
        reference = _product_reference(product, expected_event=event)
        forecast = await self._json(_safe_url(_content(product, "forecast.json")))
        parameters = _mapping(_mapping(forecast.get("model")).get("parameters"))
        windows = tuple(
            AftershockWindow(
                label=_text(window.get("label")),
                starts_at=_timestamp(window.get("timeStart")),
                ends_at=_timestamp(window.get("timeEnd")),
                probabilities=tuple(
                    AftershockProbability(
                        magnitude=_number(item.get("magnitude")),
                        probability=_number(item.get("probability")),
                        lower_count_95=_number(item.get("p95minimum")),
                        upper_count_95=_number(item.get("p95maximum")),
                    )
                    for item in (_mapping(raw) for raw in _sequence(window.get("bins")))
                ),
            )
            for window in (_mapping(raw) for raw in _sequence(forecast.get("forecast")))
        )
        return AftershockForecast(
            product=reference,
            model_name=_text(_mapping(forecast.get("model")).get("name")),
            created_at=_timestamp(forecast.get("creationTime")),
            expires_at=_timestamp(forecast.get("expireTime")),
            advisory_time_frame=_text(forecast.get("advisoryTimeFrame")),
            latitude=_number(parameters.get("regionCenterLat")),
            longitude=_number(parameters.get("regionCenterLon")),
            radius_km=_number(parameters.get("regionRadius")),
            windows=windows,
            global_scope=False,
            interpretation=(
                "USGS operational aftershock forecast for this event and stated model "
                "region; availability is not global."
            ),
        )
