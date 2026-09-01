from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.ports.weather_alerts import (
    WeatherAlertBatch,
    WeatherAlertProviderIssue,
)
from disaster_monitor.application.services.active_incidents import ActiveIncident
from disaster_monitor.application.weather_alerts import (
    WeatherAlert,
    WeatherAlertCertainty,
    WeatherAlertCoverageState,
    WeatherAlertSeverity,
    WeatherAlertsService,
    WeatherAlertUrgency,
)
from disaster_monitor.infrastructure.composition import build_current_disaster_report
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 9, 1, 2, tzinfo=UTC)


class FakeWeatherProvider:
    async def fetch_active_alerts(self, *, now: datetime) -> WeatherAlertBatch:
        return WeatherAlertBatch(
            alerts=(
                WeatherAlert(
                    provider_alert_id="fixture-alert",
                    source_id="fixture-weather",
                    publisher="Fixture Weather Authority",
                    event="Severe Thunderstorm Warning",
                    headline="Source-backed warning",
                    severity=WeatherAlertSeverity.SEVERE,
                    urgency=WeatherAlertUrgency.IMMEDIATE,
                    certainty=WeatherAlertCertainty.OBSERVED,
                    sent=now - timedelta(minutes=5),
                    effective=now - timedelta(minutes=5),
                    onset=None,
                    expires=now + timedelta(minutes=30),
                    affected_area="Fixture County",
                    geometry=None,
                    canonical_url="https://weather.example/alerts/fixture-alert",
                    retrieved_at=now,
                    attribution="Fixture attribution",
                    limitations=("Fixture limitation",),
                ),
            )
        )


class EmptyWeatherProvider:
    async def fetch_active_alerts(self, *, now: datetime) -> WeatherAlertBatch:
        return WeatherAlertBatch()


class PartialWeatherProvider(FakeWeatherProvider):
    async def fetch_active_alerts(self, *, now: datetime) -> WeatherAlertBatch:
        batch = await super().fetch_active_alerts(now=now)
        return WeatherAlertBatch(
            batch.alerts,
            WeatherAlertProviderIssue(
                "record_limit_reached",
                "The bounded fixture retained only part of the provider response.",
                partial=True,
            ),
        )


@pytest.mark.asyncio
async def test_weather_alerts_are_a_distinct_artifact_not_an_active_incident() -> None:
    snapshot = await WeatherAlertsService(
        FakeWeatherProvider(), clock=lambda: NOW
    ).execute()

    assert snapshot.coverage.state is WeatherAlertCoverageState.ALERTS_FOUND
    assert len(snapshot.alerts) == 1
    assert not isinstance(snapshot.alerts[0], ActiveIncident)

    disaster_registration_ids = {
        registration.source_id
        for registration in build_current_disaster_report(
            Settings(_env_file=None), StaticCountryCatalog()
        ).provider_registry.registrations
    }
    assert snapshot.alerts[0].source_id not in disaster_registration_ids


@pytest.mark.asyncio
async def test_weather_alerts_distinguish_successful_empty_from_partial_coverage() -> (
    None
):
    empty = await WeatherAlertsService(
        EmptyWeatherProvider(), clock=lambda: NOW
    ).execute()
    partial = await WeatherAlertsService(
        PartialWeatherProvider(), clock=lambda: NOW
    ).execute()

    assert empty.coverage.state is WeatherAlertCoverageState.NO_ACTIVE_ALERTS
    assert empty.alerts == ()
    assert empty.warnings == ()
    assert partial.coverage.state is WeatherAlertCoverageState.DEGRADED
    assert len(partial.alerts) == 1
    assert partial.warnings[0].reason_code == "record_limit_reached"
