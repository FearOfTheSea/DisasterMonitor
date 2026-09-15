"""Bounded Copernicus forecast and context adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from disaster_monitor.domain.hazard_context import (
    DroughtEpisode,
    DroughtState,
    GlofasForecast,
    GlofasForecastPoint,
    HazardLayerRole,
    WildfireContextLayer,
)
from disaster_monitor.domain.imagery.regions import (
    Coordinate,
    MultiPolygon,
    contains_coordinate,
    geometries_intersect,
    polygon_from_geojson,
)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Copernicus context record must be an object.")
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("Copernicus context collection must be an array.")
    return value


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("Copernicus numeric value is invalid.")
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError("Copernicus numeric value is invalid.") from error


def _time(value: object) -> datetime:
    text = _text(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    result = datetime.fromisoformat(text)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Copernicus timestamps must include a timezone.")
    return result


class _JsonContextAdapter:
    def __init__(
        self,
        *,
        endpoint: str,
        allowed_hosts: frozenset[str],
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
            raise ValueError("Copernicus endpoint is outside approved HTTPS hosts.")
        self._endpoint = endpoint
        self._allowed_hosts = allowed_hosts
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _document(self, *, params: dict[str, str]) -> Mapping[str, Any]:
        response = await self._client.get(
            self._endpoint, params=params, follow_redirects=False
        )
        response.raise_for_status()
        if len(response.content) > self._max_response_bytes:
            raise ValueError("Copernicus context response exceeds its byte limit.")
        if "json" not in response.headers.get("content-type", "").casefold():
            raise ValueError("Copernicus context response is not JSON.")
        return _mapping(response.json())


class GlofasForecastAdapter(_JsonContextAdapter):
    source_id = "copernicus-glofas-forecast"

    async def fetch(
        self, *, event_id: str, region: MultiPolygon, now: datetime
    ) -> GlofasForecast:
        document = await self._document(
            params={"bbox": ",".join(str(item) for item in region.bounds)}
        )
        records = [_mapping(item) for item in _list(document.get("forecasts"))]
        admitted = [
            item
            for item in records
            if contains_coordinate(
                region,
                Coordinate(
                    _number(item.get("latitude")), _number(item.get("longitude"))
                ),
            )
        ]
        if not admitted:
            raise ValueError(
                "GloFAS returned no forecast point in the selected region."
            )
        issue_times = {_time(item.get("issue_time")) for item in admitted}
        versions = {_text(item.get("model_version")) for item in admitted}
        if len(issue_times) != 1 or len(versions) != 1:
            raise ValueError("GloFAS response mixes forecast cycles or model versions.")
        return GlofasForecast(
            event_id=event_id,
            source_id=self.source_id,
            model_version=versions.pop(),
            issue_time=issue_times.pop(),
            retrieved_at=now,
            role=HazardLayerRole.MODELLED_FORECAST,
            points=tuple(
                GlofasForecastPoint(
                    station_id=_text(item.get("station_id")),
                    coordinate=Coordinate(
                        _number(item.get("latitude")),
                        _number(item.get("longitude")),
                    ),
                    valid_at=_time(item.get("valid_time")),
                    discharge_m3_s=_number(item.get("discharge_m3_s")),
                    exceedance_probability=_number(item.get("exceedance_probability")),
                    return_period_years=_number(item.get("return_period_years")),
                )
                for item in sorted(
                    admitted, key=lambda value: _time(value.get("valid_time"))
                )
            ),
            interpretation=(
                "GloFAS modelled flood forecast for the selected source-backed region; "
                "it is not an observed flood extent."
            ),
        )


class GdoDroughtAdapter(_JsonContextAdapter):
    source_id = "copernicus-global-drought-observatory"

    async def fetch(
        self, *, region: MultiPolygon, now: datetime
    ) -> tuple[DroughtEpisode, ...]:
        document = await self._document(
            params={"bbox": ",".join(str(item) for item in region.bounds)}
        )
        episodes: list[DroughtEpisode] = []
        for raw in _list(document.get("features")):
            feature = _mapping(raw)
            geometry = polygon_from_geojson(_mapping(feature.get("geometry")))
            if not geometries_intersect(region, geometry):
                continue
            properties = _mapping(feature.get("properties"))
            state_value = _text(properties.get("state")).casefold()
            episodes.append(
                DroughtEpisode(
                    episode_id=_text(feature.get("id")),
                    source_id=self.source_id,
                    dataset_version=_text(properties.get("dataset_version")),
                    geometry=geometry,
                    indicator_name=_text(properties.get("indicator")),
                    indicator_value=_number(properties.get("value")),
                    indicator_unit=_text(properties.get("unit")),
                    state=(
                        DroughtState(state_value)
                        if state_value in DroughtState
                        else DroughtState.UNKNOWN
                    ),
                    window_start=_time(properties.get("window_start")),
                    window_end=_time(properties.get("window_end")),
                    retrieved_at=now,
                )
            )
        return tuple(sorted(episodes, key=lambda item: item.episode_id))


class EffisGwisContextAdapter(_JsonContextAdapter):
    source_id = "copernicus-effis-gwis"

    async def fetch(
        self, *, event_id: str, region: MultiPolygon, now: datetime
    ) -> tuple[WildfireContextLayer, ...]:
        document = await self._document(
            params={"bbox": ",".join(str(item) for item in region.bounds)}
        )
        layers: list[WildfireContextLayer] = []
        for raw in _list(document.get("layers")):
            item = _mapping(raw)
            role = HazardLayerRole(_text(item.get("role")))
            geometry_value = item.get("geometry")
            geometry = (
                polygon_from_geojson(_mapping(geometry_value))
                if geometry_value is not None
                else None
            )
            if geometry is not None and not geometries_intersect(region, geometry):
                continue
            wms_url = _text(item.get("wms_url"))
            parsed = urlparse(wms_url)
            if parsed.scheme != "https" or parsed.hostname not in self._allowed_hosts:
                raise ValueError("EFFIS/GWIS WMS URL is outside approved hosts.")
            valid_until = item.get("valid_until")
            layers.append(
                WildfireContextLayer(
                    layer_id=_text(item.get("layer_id")),
                    event_id=event_id,
                    source_id=self.source_id,
                    role=role,
                    version=_text(item.get("version")),
                    observed_at=_time(item.get("observed_at")),
                    retrieved_at=now,
                    wms_url=wms_url,
                    geometry=geometry,
                    valid_until=_time(valid_until) if valid_until is not None else None,
                )
            )
        return tuple(layers)
