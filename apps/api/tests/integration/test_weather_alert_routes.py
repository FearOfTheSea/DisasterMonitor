from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.source_catalog import SourceCatalogService
from disaster_monitor.application.weather_alerts import (
    WeatherAlert,
    WeatherAlertCertainty,
    WeatherAlertCoverage,
    WeatherAlertCoverageState,
    WeatherAlertSeverity,
    WeatherAlertsSnapshot,
    WeatherAlertUrgency,
)
from disaster_monitor.infrastructure.composition import (
    build_current_disaster_report,
    build_source_catalog,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.main import create_app

NOW = datetime(2026, 9, 1, 2, tzinfo=UTC)


class FakeWeatherAlertsService:
    async def execute(self) -> WeatherAlertsSnapshot:
        return WeatherAlertsSnapshot(
            retrieved_at=NOW,
            alerts=(
                WeatherAlert(
                    provider_alert_id="urn:oid:http-fixture",
                    source_id="nws-weather-alerts",
                    publisher="NWS Fixture Office",
                    event="Tornado Warning",
                    headline="Tornado Warning for Fixture County",
                    severity=WeatherAlertSeverity.EXTREME,
                    urgency=WeatherAlertUrgency.IMMEDIATE,
                    certainty=WeatherAlertCertainty.OBSERVED,
                    sent=NOW,
                    effective=NOW,
                    onset=None,
                    expires=None,
                    affected_area="Fixture County",
                    geometry=None,
                    canonical_url="https://api.weather.gov/alerts/urn:oid:http-fixture",
                    retrieved_at=NOW,
                    attribution="NOAA/National Weather Service",
                    limitations=(
                        "Missing geometry is not reconstructed from place names.",
                    ),
                ),
            ),
            coverage=WeatherAlertCoverage(
                source_id="nws-weather-alerts",
                publisher="NOAA/National Weather Service",
                state=WeatherAlertCoverageState.ALERTS_FOUND,
                detail="One active alert was returned.",
                geographic_scope="United States land areas served by NWS",
                limitations=("Coverage is not global.",),
            ),
        )


def _source_catalog_service() -> SourceCatalogService:
    settings = Settings(_env_file=None)
    report = build_current_disaster_report(settings, StaticCountryCatalog())
    return SourceCatalogService(
        build_source_catalog(settings),
        report.provider_registry,
        additional_runtime_sources={
            "nws-weather-alerts": {
                "registered": True,
                "configured": True,
                "provider_tier": "primary",
                "execution_roles": ("weather_alerts",),
            }
        },
    )


@pytest.mark.asyncio
async def test_weather_alert_and_source_catalog_transport_is_bounded_and_typed() -> (
    None
):
    app = create_app(
        weather_alerts_service=FakeWeatherAlertsService(),  # type: ignore[arg-type]
        source_catalog_service=_source_catalog_service(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        weather_response = await client.get("/api/v1/weather-alerts")
        catalog_response = await client.get("/api/v1/sources")

    assert weather_response.status_code == 200
    weather = weather_response.json()
    assert weather["coverage"]["state"] == "alerts_found"
    assert weather["alerts"][0]["severity"] == "extreme"
    assert weather["alerts"][0]["geometry"] is None
    assert "description" not in weather["alerts"][0]
    assert "instruction" not in weather["alerts"][0]
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    nws = next(
        item for item in catalog["sources"] if item["source_id"] == "nws-weather-alerts"
    )
    assert nws["operational_state"]["execution_roles"] == ["weather_alerts"]
    assert "allowed_hosts" not in catalog_response.text
    assert "registered_tool_names" not in catalog_response.text
    assert "api.weather.gov" not in catalog_response.text
