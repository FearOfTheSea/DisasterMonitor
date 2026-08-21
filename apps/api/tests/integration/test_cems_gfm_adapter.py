import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.disaster import (
    DisasterQuery,
    WorldwideDisasterQuery,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    SourceAuthority,
)
from disaster_monitor.infrastructure.disaster.cems_gfm_adapter import (
    CemsGfmAdapter,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures"


def fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def country_query(country_code: str = "JPN") -> DisasterQuery:
    country = StaticCountryCatalog().get_by_alpha3(country_code)
    assert country is not None
    return DisasterQuery(
        Disaster.FLOOD, country, "recent", ("latest",), time_window_days=5
    )


def client_for(
    stac_payload: object,
    statistics_payload: object,
    requests: list[httpx.Request],
    *,
    statistics_status: int = 200,
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "stac.eodc.eu":
            payload = stac_payload
            status = 200
        else:
            payload = statistics_payload
            status = statistics_status
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode(),
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_positive_clipped_observed_flood_extent_creates_one_acquisition_event():
    requests: list[httpx.Request] = []
    snapshots: list[object] = []

    async def record_snapshot(payload: object) -> object:
        snapshots.append(payload)
        return SimpleNamespace(snapshot_id=f"snapshot:gfm:{len(snapshots)}")

    client = client_for(
        fixture("cems_gfm_stac_search.json"),
        fixture("cems_gfm_flood_statistics.json"),
        requests,
    )
    adapter = CemsGfmAdapter(
        client=client,
        geography=StaticCountryCatalog(),
        snapshot_recorder=record_snapshot,
    )

    result = await adapter.find_recent_events(country_query(), now=NOW)

    assert len(result.records) == 1
    event = result.records[0]
    assert isinstance(event, DisasterEvent)
    assert event.event_id == (
        "cems-gfm:sentinel-acquisition:"
        "S1D_IW_GRDH_1SDV_20260818T014933_20260818T014958_004188_007AC6_64D3"
    )
    assert event.provider_ids == (
        event.event_id,
        "cems-gfm:item:ENSEMBLE_FLOOD_20260818T014933_VV_AS020M_E012N033T3",
        "cems-gfm:item:ENSEMBLE_FLOOD_20260818T014933_VV_AS020M_E012N033T4",
    )
    assert event.geometry is not None
    assert event.geometry.kind.value == "point"
    assert event.geometry.coordinates[0].latitude == 32.5
    assert event.geometry.coordinates[0].longitude == 133.5
    assert event.geometry.estimated is True
    assert event.geometry.source.source_id == event.source.source_id
    assert event.geometry.source.canonical_url == event.source.canonical_url
    assert event.geography_status is EventGeographyStatus.IN_COUNTRY
    assert event.source.source_id == "cems-gfm-floods"
    assert event.source.authority is SourceAuthority.SCIENTIFIC_AUTHORITY
    assert event.source.canonical_url.startswith("https://stac.eodc.eu/")
    assert event.source.snapshot_id == "snapshot:gfm:2"
    assert len(snapshots) == 3
    assert requests[0].url.host == "stac.eodc.eu"
    assert all(
        request.url.host == "titiler.services.eodc.eu" for request in requests[1:]
    )
    statistics_body = json.loads(requests[1].content)
    assert statistics_body["geometry"]["type"] == "MultiPolygon"
    assert statistics_body["geometry"]["coordinates"][0][0][0] == [128.0, 30.0]
    await client.aclose()


@pytest.mark.asyncio
async def test_country_tile_intersection_without_country_flood_pixels_is_rejected() -> (
    None
):
    requests: list[httpx.Request] = []
    client = client_for(
        fixture("cems_gfm_stac_search.json"),
        fixture("cems_gfm_no_flood_statistics.json"),
        requests,
    )
    adapter = CemsGfmAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(country_query(), now=NOW)

    assert result.records == ()
    assert result.issues == ()
    assert len(requests) == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_stac_search_and_statistics_are_bounded_and_country_polygon_is_lon_lat():
    requests: list[httpx.Request] = []
    client = client_for(
        fixture("cems_gfm_stac_search.json"),
        fixture("cems_gfm_no_flood_statistics.json"),
        requests,
    )
    adapter = CemsGfmAdapter(client=client, geography=StaticCountryCatalog())

    await adapter.find_recent_events(country_query(), now=NOW)

    search = json.loads(requests[0].content)
    assert search["collections"] == ["GFM"]
    assert search["limit"] == 50
    assert search["datetime"] == "2026-08-13T12:00:00Z/2026-08-18T12:00:00Z"
    assert search["sortby"] == [{"field": "datetime", "direction": "desc"}]
    country_geometry = search["intersects"]
    assert country_geometry["type"] == "MultiPolygon"
    assert country_geometry["coordinates"][0][0][0] == [128.0, 30.0]
    statistics_query = dict(requests[1].url.params.multi_items())
    assert statistics_query == {
        "url": "https://data.eodc.eu/collections/GFM_LAYERS/flood_extent/AS020M/2026/08/18/ENSEMBLE_FLOOD_20260818T014933_VV_AS020M_E012N033T3.tif",
        "bidx": "1",
        "categorical": "true",
        "c": "1",
        "max_size": "1024",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_worldwide_scan_is_bounded_and_uses_tile_center_geometry():
    requests: list[httpx.Request] = []
    client = client_for(
        fixture("cems_gfm_stac_search.json"),
        fixture("cems_gfm_flood_statistics.json"),
        requests,
    )
    adapter = CemsGfmAdapter(client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.FLOOD, time_window_days=365, limit=999),
        now=NOW,
    )

    assert len(result.records) == 1
    event = result.records[0]
    assert event.geometry is not None
    assert event.geometry.coordinates[0].latitude == 32.5
    assert event.geometry.coordinates[0].longitude == 133.5
    assert event.geometry.estimated is True
    search = json.loads(requests[0].content)
    assert search["limit"] == 50
    assert search["bbox"] == [-180.0, -90.0, 180.0, 90.0]
    assert search["datetime"] == "2026-07-19T12:00:00Z/2026-08-18T12:00:00Z"
    await client.aclose()


@pytest.mark.asyncio
async def test_coalesced_acquisition_uses_deterministic_tile_center() -> None:
    payload = fixture("cems_gfm_stac_search.json")
    features = payload["features"]
    assert isinstance(features, list)
    payload["features"] = list(reversed(features))
    requests: list[httpx.Request] = []
    client = client_for(
        payload,
        fixture("cems_gfm_flood_statistics.json"),
        requests,
    )
    adapter = CemsGfmAdapter(
        client=client,
        geography=StaticCountryCatalog(),
    )

    result = await adapter.find_recent_events(country_query(), now=NOW)

    assert len(result.records) == 1
    event = result.records[0]
    assert isinstance(event, DisasterEvent)
    assert event.geometry is not None
    assert event.geometry.coordinates[0].latitude == 32.5
    assert event.geometry.coordinates[0].longitude == 133.5
    assert event.source.canonical_url.endswith("E012N033T3")
    assert event.provider_ids == (
        event.event_id,
        "cems-gfm:item:ENSEMBLE_FLOOD_20260818T014933_VV_AS020M_E012N033T4",
        "cems-gfm:item:ENSEMBLE_FLOOD_20260818T014933_VV_AS020M_E012N033T3",
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_malformed_or_untrusted_assets_fail_closed() -> None:
    payload = fixture("cems_gfm_stac_search.json")
    features = payload["features"]
    assert isinstance(features, list)
    first = features[0]
    assert isinstance(first, dict)
    for feature in features:
        assert isinstance(feature, dict)
        assets = feature["assets"]
        assert isinstance(assets, dict)
        assets["ensemble_flood_extent"]["href"] = "https://evil.example/flood.tif"
    requests: list[httpx.Request] = []
    client = client_for(payload, fixture("cems_gfm_flood_statistics.json"), requests)
    adapter = CemsGfmAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(country_query(), now=NOW)

    assert result.records == ()
    assert result.issues[0].reason_code == "source_policy_violation"
    assert len(requests) == 1
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_value", [None, {}])
async def test_missing_or_malformed_assets_fail_closed(asset_value: object) -> None:
    payload = fixture("cems_gfm_stac_search.json")
    features = payload["features"]
    assert isinstance(features, list)
    for feature in features:
        assert isinstance(feature, dict)
        assets = feature["assets"]
        assert isinstance(assets, dict)
        assets["ensemble_flood_extent"] = asset_value
    requests: list[httpx.Request] = []
    client = client_for(payload, fixture("cems_gfm_flood_statistics.json"), requests)
    adapter = CemsGfmAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(country_query(), now=NOW)

    assert result.records == ()
    assert [issue.reason_code for issue in result.issues] == [
        "invalid_record",
        "invalid_record",
    ]
    assert len(requests) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_non_flood_disasters_make_no_network_request() -> None:
    requests: list[httpx.Request] = []
    client = client_for({}, {}, requests)
    adapter = CemsGfmAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(
        DisasterQuery(Disaster.EARTHQUAKE, country_query().country, "recent", ()),
        now=NOW,
    )

    assert result.records == ()
    assert requests == []
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_http_failures_remain_typed() -> None:
    requests: list[httpx.Request] = []
    client = client_for(
        fixture("cems_gfm_stac_search.json"),
        fixture("cems_gfm_flood_statistics.json"),
        requests,
        statistics_status=503,
    )
    adapter = CemsGfmAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(country_query(), now=NOW)

    assert result.records == ()
    assert result.issues[0].reason_code == "http_server_error"
    assert result.issues[0].retryable
    await client.aclose()
