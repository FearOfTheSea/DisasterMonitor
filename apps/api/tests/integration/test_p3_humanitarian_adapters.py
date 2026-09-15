from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.domain.humanitarian import HumanitarianIndicatorKind
from disaster_monitor.infrastructure.humanitarian.hdx_hapi import HdxHapiContextAdapter
from disaster_monitor.infrastructure.humanitarian.iom_dtm import IomDtmContextAdapter

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_hdx_hapi_admits_only_rows_with_exact_time_and_license_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        common = {
            "location_code": "VNM",
            "admin_level": 0,
            "resource_hdx_id": "resource-1",
            "dataset_hdx_stub": "vietnam-context",
            "dataset_hdx_license": "Creative Commons Attribution 4.0",
            "reference_period_start": "2026-01-01",
            "reference_period_end": "2026-08-31",
        }
        if path.endswith("baseline-population"):
            return httpx.Response(
                200,
                json=[
                    {
                        **common,
                        "population": 1000,
                        "gender": "all",
                        "age_range": "all",
                    }
                ],
            )
        if path.endswith("internally-displaced-persons"):
            return httpx.Response(
                200,
                json=[
                    {
                        **common,
                        "population": 250,
                        "operation": "Flood tracking",
                        "reporting_round": 3,
                    }
                ],
            )
        if path.endswith("food-security"):
            return httpx.Response(
                200,
                json=[
                    {
                        **common,
                        "population_in_phase": 50,
                        "ipc_phase": "3",
                        "ipc_type": "current",
                    }
                ],
            )
        if path.endswith("operational-presence"):
            return httpx.Response(
                200,
                json=[
                    {
                        **common,
                        "org_name": "Example Relief Organization",
                        "org_acronym": "ERO",
                        "sector_name": "Shelter",
                    }
                ],
            )
        raise AssertionError(path)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HdxHapiContextAdapter(
        app_identifier="test-app-id", client=client, clock=lambda: NOW
    )

    indicators = await adapter.indicators("VNM")
    presence = await adapter.operational_presence("VNM")

    assert {item.kind for item in indicators} == {
        HumanitarianIndicatorKind.BASELINE_POPULATION,
        HumanitarianIndicatorKind.DISPLACED_PEOPLE,
        HumanitarianIndicatorKind.FOOD_INSECURITY,
    }
    assert all(
        item.license_name == "Creative Commons Attribution 4.0" for item in indicators
    )
    assert indicators[1].causal_attribution is False
    assert presence[0].organization == "Example Relief Organization"
    assert presence[0].dataset_updated_at == datetime(2026, 8, 31, tzinfo=UTC)
    await client.aclose()


@pytest.mark.asyncio
async def test_hdx_hapi_omits_rows_without_dataset_license() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("operational-presence"):
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json=[
                {
                    "location_code": "VNM",
                    "resource_hdx_id": "resource-1",
                    "population": 100,
                    "reference_period_start": "2026-01-01",
                    "reference_period_end": "2026-08-31",
                }
            ],
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HdxHapiContextAdapter(
        app_identifier="test-app-id", client=client, clock=lambda: NOW
    )
    assert await adapter.indicators("VNM") == ()
    await client.aclose()


@pytest.mark.asyncio
async def test_iom_dtm_preserves_admin_and_time_without_event_causality() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Ocp-Apim-Subscription-Key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "dtm-row-1",
                        "countryCode": "VNM",
                        "admin1Code": "VN-01",
                        "admin1Name": "Test Province",
                        "individuals": 300,
                        "reportingDate": "2026-09-01T00:00:00Z",
                        "datasetUrl": "https://dtm.iom.int/datasets/example",
                        "license": "IOM DTM public data terms",
                        "round": "4",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = IomDtmContextAdapter(
        api_url="https://api.dtm.iom.int/v3/displacement",
        subscription_key="test-key",
        client=client,
        clock=lambda: NOW,
    )
    records = await adapter.indicators("VNM")

    assert len(records) == 1
    assert records[0].admin1_code == "VN-01"
    assert records[0].causal_attribution is False
    assert dict(records[0].dimensions)["round"] == "4"
    await client.aclose()
