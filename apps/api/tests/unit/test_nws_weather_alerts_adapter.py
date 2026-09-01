import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from disaster_monitor.application.weather_alerts import (
    WeatherAlertCoverageState,
    WeatherAlertsService,
)
from disaster_monitor.infrastructure.weather.nws_alerts import NwsWeatherAlertsAdapter

NOW = datetime(2026, 9, 1, 2, tzinfo=UTC)
FIXTURE = Path(__file__).parents[1] / "fixtures" / "nws_active_alerts.json"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2)


@pytest.mark.asyncio
async def test_adapter_preserves_cap_semantics_and_only_source_geometry() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=json.loads(FIXTURE.read_text()),
            headers={"content-type": "application/geo+json"},
        )

    adapter = NwsWeatherAlertsAdapter(
        client=_client(handler), maximum_response_bytes=1_000_000
    )
    try:
        batch = await adapter.fetch_active_alerts(now=NOW)
    finally:
        await adapter.aclose()

    assert len(requests) == 1
    assert requests[0].url.host == "api.weather.gov"
    assert requests[0].url.path == "/alerts/active"
    assert dict(requests[0].url.params) == {
        "status": "actual",
        "message_type": "alert,update",
        "region_type": "land",
    }
    assert requests[0].headers["accept"] == "application/geo+json"
    assert "DisasterMonitor" in requests[0].headers["user-agent"]
    assert batch.issue is None
    assert [alert.provider_alert_id for alert in batch.alerts] == [
        "urn:oid:fixture-severe-update",
        "urn:oid:fixture-unknown-no-geometry",
    ]
    severe, unknown = batch.alerts
    assert severe.publisher == "NWS Salt Lake City UT"
    assert severe.event == "Flash Flood Warning"
    assert severe.severity.value == "severe"
    assert severe.urgency.value == "immediate"
    assert severe.certainty.value == "likely"
    assert severe.effective == datetime(2026, 9, 1, 1, 18, tzinfo=UTC)
    assert severe.geometry is not None
    assert severe.geometry.rings[0][0].longitude == -112.93
    assert severe.geometry.rings[0][0].latitude == 37.0
    assert severe.canonical_url.endswith("urn:oid:fixture-severe-update")
    assert severe.retrieved_at == NOW
    assert unknown.severity.value == "unknown"
    assert unknown.urgency.value == "unknown"
    assert unknown.certainty.value == "unknown"
    assert unknown.geometry is None
    assert unknown.headline is None


@pytest.mark.asyncio
async def test_adapter_distinguishes_successful_empty_from_source_failure() -> None:
    empty_adapter = NwsWeatherAlertsAdapter(
        client=_client(
            lambda request: httpx.Response(
                200,
                json={"type": "FeatureCollection", "features": []},
                headers={"content-type": "application/geo+json"},
            )
        )
    )
    failure_adapter = NwsWeatherAlertsAdapter(
        client=_client(lambda request: httpx.Response(503, json={"detail": "down"}))
    )
    try:
        empty = await WeatherAlertsService(empty_adapter, clock=lambda: NOW).execute()
        failed = await WeatherAlertsService(
            failure_adapter, clock=lambda: NOW
        ).execute()
    finally:
        await empty_adapter.aclose()
        await failure_adapter.aclose()

    assert empty.alerts == ()
    assert empty.coverage.state is WeatherAlertCoverageState.NO_ACTIVE_ALERTS
    assert failed.alerts == ()
    assert failed.coverage.state is WeatherAlertCoverageState.UNAVAILABLE
    assert failed.warnings[0].reason_code == "http_server_error"


@pytest.mark.asyncio
async def test_adapter_reports_malformed_siblings_and_enforces_record_ceiling() -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["features"].insert(0, {"type": "Feature", "properties": {}})
    adapter = NwsWeatherAlertsAdapter(
        client=_client(
            lambda request: httpx.Response(
                200,
                json=payload,
                headers={"content-type": "application/geo+json"},
            )
        ),
        maximum_records=3,
    )
    try:
        batch = await adapter.fetch_active_alerts(now=NOW)
    finally:
        await adapter.aclose()

    assert batch.issue is not None
    assert batch.issue.reason_code == "record_limit_reached"
    assert batch.issue.partial is True
    assert len(batch.alerts) == 2
