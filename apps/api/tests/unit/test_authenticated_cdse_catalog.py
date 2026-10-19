"""The documented authenticated catalog retains targeting and bounded access."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.ports.ground_imagery.catalog import (
    CatalogSearchError,
    GroundImageryCatalogQuery,
)
from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole
from disaster_monitor.domain.imagery.regions import polygon_from_geojson
from disaster_monitor.infrastructure.ground_imagery.cdse_catalog import CDSEStacCatalog

ENDPOINT = "https://sh.dataspace.copernicus.eu/catalog/v1/search"


def query():
    return GroundImageryCatalogQuery(
        Sensor.SENTINEL_2,
        polygon_from_geojson(
            {
                "type": "Polygon",
                "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
            }
        ),
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 3, tzinfo=UTC),
        TemporalRole.LATEST_USEFUL,
    )


@pytest.mark.asyncio
async def test_authenticated_catalog_uses_credentials_once_and_preserves_next_page():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.host == "identity.dataspace.copernicus.eu":
            return httpx.Response(
                200, json={"access_token": "private-token", "expires_in": 300}
            )
        assert request.url == ENDPOINT
        assert request.headers["Authorization"] == "Bearer private-token"
        body = json.loads(request.content)
        assert body["intersects"] == query().geometry.as_geojson()
        assert body["datetime"] == "2026-10-01T00:00:00Z/2026-10-03T00:00:00Z"
        return httpx.Response(
            200,
            json={"features": [], "context": {"next": 2}}
            if "next" not in body
            else {"features": []},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        catalog = CDSEStacCatalog(
            endpoint=ENDPOINT,
            client=client,
            client_id="configured-client",
            client_secret="configured-secret",
        )
        first = await catalog.search(query())
        assert first.next_cursor == "2"
        assert not first.scan_complete
        second = await catalog.search(replace(query(), cursor=first.next_cursor))
        assert second.scan_complete
    assert len(requests) == 3
    assert json.loads(requests[-1].content)["next"] == 2


@pytest.mark.asyncio
async def test_authenticated_catalog_reports_credentials_failure_without_public_retry():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(401, json={"error": "private-provider-detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        catalog = CDSEStacCatalog(
            endpoint=ENDPOINT,
            client=client,
            client_id="configured-client",
            client_secret="configured-secret",
        )
        with pytest.raises(CatalogSearchError) as failure:
            await catalog.search(query())
    assert failure.value.reason_code == "credentials_required"
    assert "private-provider-detail" not in str(failure.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_authenticated_catalog_accepts_decimal_string_continuation():
    def respond(request):
        if request.url.host == "identity.dataspace.copernicus.eu":
            return httpx.Response(
                200, json={"access_token": "token", "expires_in": 300}
            )
        body = json.loads(request.content)
        if "next" not in body:
            return httpx.Response(
                200, json={"features": [], "context": {"next": "100"}}
            )
        assert body["next"] == 100
        return httpx.Response(200, json={"features": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        catalog = CDSEStacCatalog(
            endpoint=ENDPOINT, client=client, client_id="id", client_secret="secret"
        )
        first = await catalog.search(query())
        assert first.next_cursor == "100"
        second = await catalog.search(replace(query(), cursor=first.next_cursor))
        assert second.scan_complete


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cursor",
    [True, "https://other.example/next", "-1", "0", "1000000", "\u0661\u0660\u0660"],
)
async def test_authenticated_catalog_rejects_unsafe_continuations(cursor):
    def respond(request):
        if request.url.host == "identity.dataspace.copernicus.eu":
            return httpx.Response(
                200, json={"access_token": "token", "expires_in": 300}
            )
        return httpx.Response(200, json={"features": [], "context": {"next": cursor}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        catalog = CDSEStacCatalog(
            endpoint=ENDPOINT, client=client, client_id="id", client_secret="secret"
        )
        with pytest.raises(CatalogSearchError) as failure:
            await catalog.search(query())
        assert failure.value.reason_code == "catalog_schema_invalid"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://sh.dataspace.copernicus.eu:444/catalog/v1/search",
        "https://sh.dataspace.copernicus.eu/other",
        "https://sh.dataspace.copernicus.eu.attacker.test/catalog/v1/search",
    ],
)
def test_credentials_cannot_be_sent_to_other_authorities_or_paths(endpoint):
    with pytest.raises(ValueError):
        CDSEStacCatalog(endpoint=endpoint, client_id="id", client_secret="secret")


@pytest.mark.asyncio
async def test_catalog_safe_container_suffix_does_not_change_product_identity():
    def respond(request):
        if request.url.host == "identity.dataspace.copernicus.eu":
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "id": "S2A_MSIL2A_TEST.SAFE",
                        "geometry": query().geometry.as_geojson(),
                        "properties": {"datetime": "2026-10-02T12:00:00Z"},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        catalog = CDSEStacCatalog(
            endpoint=ENDPOINT, client=client, client_id="id", client_secret="secret"
        )
        page = await catalog.search(query())
    assert page.observations[0].identity.product_id == "S2A_MSIL2A_TEST"
