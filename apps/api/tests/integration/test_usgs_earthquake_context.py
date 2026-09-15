import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from disaster_monitor.application.earthquake_context import EarthquakeContextService
from disaster_monitor.domain.earthquake_context import (
    EarthquakeContext,
    GroundFailureKind,
    ShakeMeasure,
)
from disaster_monitor.infrastructure.composition import AppDependencyOverrides
from disaster_monitor.infrastructure.earthquake.usgs_products import (
    UsgsEarthquakeProductsAdapter,
)
from disaster_monitor.main import create_app

NOW = datetime(2026, 9, 14, 12, 5, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures"


class FixedEarthquakeContextReader:
    def __init__(self, context: EarthquakeContext) -> None:
        self._context = context

    async def fetch(self, event_id: str, *, now: datetime) -> EarthquakeContext:
        assert event_id == self._context.event_id
        return self._context

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_usgs_products_preserve_product_roles_and_event_linkage() -> None:
    fixture_by_path = {
        "/earthquakes/feed/v1.0/detail/us7000fixture.geojson": (
            "usgs_event_products.json"
        ),
        "/products/exposures.json": "usgs_pager_exposures.json",
        "/products/alerts.json": "usgs_pager_alerts.json",
        "/products/forecast.json": "usgs_oaf_forecast.json",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        fixture = fixture_by_path.get(request.url.path)
        if fixture is None:
            return httpx.Response(404)
        return httpx.Response(
            200,
            json=json.loads((FIXTURES / fixture).read_text()),
            headers={"content-type": "application/json"},
        )

    adapter = UsgsEarthquakeProductsAdapter(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2)
    )
    try:
        context = await adapter.fetch("usgs:us7000fixture", now=NOW)
    finally:
        await adapter.aclose()

    assert context.event_id == "usgs:us7000fixture"
    assert [layer.measure for layer in context.shakemap_layers] == [
        ShakeMeasure.MMI,
        ShakeMeasure.PGA,
        ShakeMeasure.PGV,
    ]
    assert context.shakemap_layers[0].unit == "MMI"
    assert context.shakemap_layers[1].unit == "%g"
    assert context.shakemap_layers[2].unit == "cm/s"
    assert context.shakemap_layers[0].product.version == "4"
    assert context.shakemap_layers[0].legend_url.endswith("mmi-legend.png")
    assert context.pager is not None
    assert context.pager.alert_level == "orange"
    assert context.pager.product.version == "2"
    assert context.pager.exposure_by_intensity[2].population == 4000
    assert context.pager.fatality_probability_bins[1].probability == 0.45
    assert context.pager.economic_loss_probability_bins[0].minimum == 1_000_000
    assert "modelled" in context.pager.interpretation.casefold()
    assert [item.kind for item in context.ground_failure] == [
        GroundFailureKind.LANDSLIDE,
        GroundFailureKind.LIQUEFACTION,
    ]
    assert context.ground_failure[0].hazard_value == pytest.approx(0.18)
    assert context.aftershock_forecast is not None
    assert context.aftershock_forecast.global_scope is False
    assert context.aftershock_forecast.windows[0].probabilities[
        0
    ].probability == pytest.approx(0.12)

    app = create_app(
        overrides=AppDependencyOverrides(
            earthquake_context_service=EarthquakeContextService(
                FixedEarthquakeContextReader(context)
            )
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/earthquakes/usgs%3Aus7000fixture/context")
    assert response.status_code == 200
    payload = response.json()
    assert payload["shakemap_layers"][0]["measure"] == "mmi"
    assert payload["pager"]["interpretation"].startswith("PAGER is a modelled")


@pytest.mark.asyncio
async def test_usgs_products_fail_closed_when_product_event_identity_differs() -> None:
    document = json.loads((FIXTURES / "usgs_event_products.json").read_text())
    document["properties"]["products"]["shakemap"][0]["properties"][
        "eventsourcecode"
    ] = "different"
    adapter = UsgsEarthquakeProductsAdapter(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=document,
                    headers={"content-type": "application/json"},
                )
            )
        )
    )
    try:
        with pytest.raises(ValueError, match="event identity"):
            await adapter.fetch("usgs:us7000fixture", now=NOW)
    finally:
        await adapter.aclose()
