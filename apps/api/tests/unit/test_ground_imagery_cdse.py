from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.ports.ground_imagery.catalog import (
    GroundImageryCatalogQuery,
)
from disaster_monitor.domain.imagery.observations import Sensor, TemporalRole
from disaster_monitor.domain.imagery.regions import polygon_from_geojson
from disaster_monitor.infrastructure.ground_imagery.cdse_catalog import (
    CDSEStacCatalog,
)


def _query() -> GroundImageryCatalogQuery:
    return GroundImageryCatalogQuery(
        sensor=Sensor.SENTINEL_2,
        geometry=polygon_from_geojson(
            {
                "type": "Polygon",
                "coordinates": [[[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]],
            }
        ),
        start=datetime(2024, 5, 1, tzinfo=UTC),
        end=datetime(2024, 5, 10, tzinfo=UTC),
        role=TemporalRole.LATEST_USEFUL,
    )


@pytest.mark.asyncio
async def test_cdse_stac_search_maps_metadata_and_keeps_assets_as_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "context": {"matched": 1, "returned": 1},
                "features": [
                    {
                        "type": "Feature",
                        "id": "S2B_TEST",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[10, 1], [11, 1], [11, 2], [10, 2], [10, 1]]
                            ],
                        },
                        "properties": {
                            "datetime": "2024-05-05T12:00:00Z",
                            "platform": "sentinel-2b",
                            "eo:cloud_cover": 100,
                            "s2:processing_baseline": "05.10",
                        },
                        "links": [
                            {
                                "rel": "self",
                                "href": "https://stac.dataspace.copernicus.eu/v1/items/S2B_TEST",
                            }
                        ],
                        "assets": {
                            "B02": {
                                "href": "https://catalogue.dataspace.copernicus.eu/assets/B02.tif"
                            },
                            "bad": {"href": "file:///etc/passwd"},
                        },
                    }
                ],
            },
        )

    catalog = CDSEStacCatalog(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        maximum_response_bytes=100_000,
    )
    try:
        page = await catalog.search(_query())
    finally:
        await catalog.aclose()

    assert len(requests) == 1
    assert requests[0].method == "POST"
    payload = requests[0].content.decode()
    assert '"sentinel-2-l2a"' in payload
    assert "2024-05-01T00:00:00Z/2024-05-10T00:00:00Z" in payload
    assert page.scan_complete is True
    observation = page.observations[0]
    assert observation.identity.product_id == "S2B_TEST"
    assert observation.cloud_cover_fraction == 1
    assert observation.identity.processing_version == "05.10"
    assert observation.assets == (
        (
            "B02",
            "https://catalogue.dataspace.copernicus.eu/assets/B02.tif",
        ),
    )


def test_cdse_rejects_unregistered_authority() -> None:
    with pytest.raises(ValueError):
        CDSEStacCatalog(endpoint="https://example.test/search")
