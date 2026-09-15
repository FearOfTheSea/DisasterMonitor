from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.domain.imagery.regions import polygon_from_geojson
from disaster_monitor.infrastructure.ground_imagery.openaerialmap_stac import (
    OpenAerialMapStacCatalog,
)

NOW = datetime(2026, 9, 15, tzinfo=UTC)
REGION = polygon_from_geojson(
    {
        "type": "Polygon",
        "coordinates": [[[106, 10], [107, 10], [107, 11], [106, 11], [106, 10]]],
    }
)


@pytest.mark.asyncio
async def test_oam_search_is_incident_bounded_and_preserves_open_imagery_metadata() -> (
    None
):
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "oam-item-1",
                        "geometry": REGION.as_geojson(),
                        "bbox": [106, 10, 107, 11],
                        "properties": {
                            "datetime": "2026-09-14T08:00:00Z",
                            "created": "2026-09-14T10:00:00Z",
                            "license": "CC-BY-4.0",
                            "providers": [{"name": "Humanitarian OpenStreetMap Team"}],
                            "oam:creator": "Local drone team",
                        },
                        "assets": {
                            "visual": {
                                "href": (
                                    "https://s3.amazonaws.com/oin-hotosm-temp/"
                                    "oam-item-1.tif"
                                ),
                                "type": (
                                    "image/tiff; application=geotiff; "
                                    "profile=cloud-optimized"
                                ),
                                "roles": ["data", "visual"],
                            }
                        },
                        "links": [
                            {
                                "rel": "self",
                                "href": "https://api.imagery.hotosm.org/stac/collections/openaerialmap/items/oam-item-1",
                            }
                        ],
                    }
                ],
            },
            headers={"content-type": "application/geo+json"},
        )

    catalog = OpenAerialMapStacCatalog(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    try:
        result = await catalog.search(
            incident_id="wildfire:1",
            region=REGION,
            starts_at=datetime(2026, 9, 13, tzinfo=UTC),
            ends_at=NOW,
            now=NOW,
        )
    finally:
        await catalog.aclose()

    assert seen[0]["bbox"] == [106, 10, 107, 11]
    assert seen[0]["datetime"] == "2026-09-13T00:00:00+00:00/2026-09-15T00:00:00+00:00"
    assert result.items[0].incident_id == "wildfire:1"
    assert result.items[0].license_name == "CC-BY-4.0"
    assert result.items[0].creator == "Local drone team"
    assert result.availability_statement == "1 optional open aerial image found"
