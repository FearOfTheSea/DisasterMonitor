from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.domain.exposure import RouteProfile
from disaster_monitor.domain.imagery.regions import Coordinate
from disaster_monitor.infrastructure.exposure.osrm import SelfHostedOsrmAdapter

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_self_hosted_osrm_returns_visualization_context_with_provenance() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/route/v1/driving/106.1,21.1;106.2,21.2")
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 1500,
                        "duration": 300,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[106.1, 21.1], [106.2, 21.2]],
                        },
                    }
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = SelfHostedOsrmAdapter(
        base_url="http://127.0.0.1:5000",
        data_version="geofabrik-2026-09-01",
        client=client,
        clock=lambda: NOW,
    )
    result = await adapter.route(
        Coordinate(21.1, 106.1),
        Coordinate(21.2, 106.2),
        RouteProfile.DRIVING,
    )

    assert result.distance_m == 1500
    assert result.provider == "self-hosted-osrm"
    assert result.data_version == "geofabrik-2026-09-01"
    assert "not an evacuation route" in result.limitation
    await client.aclose()


def test_osrm_rejects_non_local_routing_hosts() -> None:
    with pytest.raises(ValueError, match="self-hosted"):
        SelfHostedOsrmAdapter(
            base_url="https://router.project-osrm.org",
            data_version="unknown",
        )
