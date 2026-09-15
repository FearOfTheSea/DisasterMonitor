from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.domain.hazard_context import (
    DroughtState,
    HazardLayerRole,
)
from disaster_monitor.domain.imagery.regions import polygon_from_geojson
from disaster_monitor.infrastructure.hazard_context.copernicus import (
    EffisGwisContextAdapter,
    GdoDroughtAdapter,
    GlofasForecastAdapter,
)

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
REGION = polygon_from_geojson(
    {
        "type": "Polygon",
        "coordinates": [[[10, 45], [11, 45], [11, 46], [10, 46], [10, 45]]],
    }
)


@pytest.mark.asyncio
async def test_glofas_preserves_issue_time_probability_and_return_period() -> None:
    document = {
        "forecasts": [
            {
                "station_id": "station-1",
                "latitude": 45.5,
                "longitude": 10.5,
                "issue_time": "2026-09-14T00:00:00Z",
                "valid_time": "2026-09-16T00:00:00Z",
                "discharge_m3_s": 420,
                "exceedance_probability": 0.7,
                "return_period_years": 20,
                "model_version": "GloFAS-v4.0",
            }
        ]
    }
    adapter = GlofasForecastAdapter(
        endpoint="https://glofas.example/forecast",
        allowed_hosts=frozenset({"glofas.example"}),
        client=_client(document),
    )
    try:
        result = await adapter.fetch(event_id="flood:1", region=REGION, now=NOW)
    finally:
        await adapter.aclose()

    assert result.event_id == "flood:1"
    assert result.issue_time.isoformat() == "2026-09-14T00:00:00+00:00"
    assert result.points[0].exceedance_probability == pytest.approx(0.7)
    assert result.points[0].return_period_years == 20
    assert result.role is HazardLayerRole.MODELLED_FORECAST


@pytest.mark.asyncio
async def test_gdo_models_slow_onset_region_and_indicator_window() -> None:
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "gdo:cdi:region-1:2026-09",
                "type": "Feature",
                "geometry": REGION.as_geojson(),
                "properties": {
                    "indicator": "Combined Drought Indicator",
                    "value": 3,
                    "unit": "class",
                    "state": "warning",
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-09-10T00:00:00Z",
                    "dataset_version": "GDO-CDI-2026-09-10",
                },
            }
        ],
    }
    adapter = GdoDroughtAdapter(
        endpoint="https://gdo.example/indicators",
        allowed_hosts=frozenset({"gdo.example"}),
        client=_client(document),
    )
    try:
        episodes = await adapter.fetch(region=REGION, now=NOW)
    finally:
        await adapter.aclose()

    assert episodes[0].state is DroughtState.WARNING
    assert episodes[0].slow_onset is True
    assert episodes[0].window_start < episodes[0].window_end


@pytest.mark.asyncio
async def test_effis_gwis_does_not_flatten_detection_perimeter_and_danger() -> None:
    document = {
        "layers": [
            {
                "layer_id": "effis-active-fires",
                "role": "detection",
                "observed_at": "2026-09-14T08:00:00Z",
                "version": "2026-09-14T08",
                "wms_url": "https://effis.example/wms",
                "geometry": REGION.as_geojson(),
            },
            {
                "layer_id": "effis-burned-area",
                "role": "burned_area_perimeter",
                "observed_at": "2026-09-14T06:00:00Z",
                "version": "2026-09-14T06",
                "wms_url": "https://effis.example/wms",
                "geometry": REGION.as_geojson(),
            },
            {
                "layer_id": "gwis-fire-danger",
                "role": "forecast_danger",
                "observed_at": "2026-09-14T00:00:00Z",
                "valid_until": "2026-09-15T00:00:00Z",
                "version": "2026-09-14",
                "wms_url": "https://effis.example/wms",
            },
        ]
    }
    adapter = EffisGwisContextAdapter(
        endpoint="https://effis.example/context",
        allowed_hosts=frozenset({"effis.example"}),
        client=_client(document),
    )
    try:
        layers = await adapter.fetch(event_id="wildfire:1", region=REGION, now=NOW)
    finally:
        await adapter.aclose()

    assert [item.role for item in layers] == [
        HazardLayerRole.DETECTION,
        HazardLayerRole.BURNED_AREA_PERIMETER,
        HazardLayerRole.FORECAST_DANGER,
    ]
    assert layers[2].geometry is None
    assert all(item.establishes_incident is False for item in layers)


def _client(document: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=document,
                headers={"content-type": "application/json"},
            )
        )
    )
