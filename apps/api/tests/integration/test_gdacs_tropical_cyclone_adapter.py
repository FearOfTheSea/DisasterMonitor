import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.disaster import WorldwideDisasterQuery
from disaster_monitor.domain.disaster import Hazard, MeasurementKind
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.gdacs_adapter import (
    GdacsTropicalCycloneAdapter,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "gdacs_tropical_cyclone_search.json"
)


def gdacs_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def client_for(
    payload: object,
    requests: list[httpx.Request],
    *,
    status: int = 200,
    content_type: str = "application/json",
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        content = (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )
        return httpx.Response(
            status,
            headers={"content-type": content_type},
            content=content,
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_gdacs_translates_fixed_search_fixture_with_provenance() -> None:
    requests: list[httpx.Request] = []
    snapshots: list[object] = []

    async def record_snapshot(payload: object) -> object:
        snapshots.append(payload)
        return SimpleNamespace(snapshot_id="snapshot:gdacs-fixture")

    client = client_for(gdacs_payload(), requests)
    adapter = GdacsTropicalCycloneAdapter(
        client=client, snapshot_recorder=record_snapshot
    )

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE), now=NOW
    )

    event = result.records[0]
    assert [item.event_id for item in result.records] == [
        "gdacs:tc:1001303",
        "gdacs:tc:1001304",
    ]
    assert event.hazard is Hazard.TROPICAL_CYCLONE
    assert event.location == "United States"
    assert event.event_time == datetime(2026, 8, 18, 9, tzinfo=UTC)
    assert event.provider_ids == ("gdacs:tc:1001303", "gdacs:tc:1001303:24")
    assert event.source.source_id == "gdacs-tropical-cyclones"
    assert event.source.canonical_url.startswith("https://www.gdacs.org/")
    assert event.source.published_at is None
    assert event.source.updated_at == datetime(2026, 8, 18, 11, 37, 9, tzinfo=UTC)
    assert event.source.retrieved_at == NOW
    assert event.source.snapshot_id == "snapshot:gdacs-fixture"
    assert event.geometry is not None
    assert event.geometry.coordinates[0].latitude == 20.4
    assert event.geometry.coordinates[0].longitude == -166.1
    assert [(item.kind, item.value) for item in event.measurements] == [
        (MeasurementKind.SEVERITY, "Green")
    ]
    assert not hasattr(event, "country")
    assert len(snapshots) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_query_is_tropical_cyclone_only_and_bounded() -> None:
    requests: list[httpx.Request] = []
    client = client_for(gdacs_payload(), requests)
    adapter = GdacsTropicalCycloneAdapter(client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE, time_window_days=5, limit=7),
        now=NOW,
    )
    params = dict(requests[0].url.params.multi_items())

    assert params == {
        "eventlist": "TC",
        "fromDate": (NOW - timedelta(days=5)).isoformat(),
        "toDate": NOW.isoformat(),
        "pageSize": "7",
        "pageNumber": "1",
    }
    assert result.records

    wrong_hazard = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Hazard.EARTHQUAKE), now=NOW
    )
    assert wrong_hazard.records == ()
    assert len(requests) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_keeps_valid_records_when_one_record_is_malformed() -> None:
    payload = gdacs_payload()
    features = payload["features"]
    assert isinstance(features, list)
    features.append({"type": "Feature", "properties": {}})
    requests: list[httpx.Request] = []
    client = client_for(payload, requests)

    result = await GdacsTropicalCycloneAdapter(client=client).find_worldwide_events(
        WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE), now=NOW
    )

    assert len(result.records) == 2
    assert [issue.reason_code for issue in result.issues] == ["invalid_record"]
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_rejects_malformed_top_level_response() -> None:
    requests: list[httpx.Request] = []
    client = client_for({"type": "FeatureCollection"}, requests)

    with pytest.raises(DisasterProviderResponseError):
        await GdacsTropicalCycloneAdapter(client=client).find_worldwide_events(
            WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE), now=NOW
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_replaces_untrusted_event_url_with_approved_source_url() -> None:
    payload = gdacs_payload()
    features = payload["features"]
    assert isinstance(features, list)
    first = features[0]
    assert isinstance(first, dict)
    properties = first["properties"]
    assert isinstance(properties, dict)
    urls = properties["url"]
    assert isinstance(urls, dict)
    urls["details"] = "https://evil.example/tropical-cyclone"
    requests: list[httpx.Request] = []
    client = client_for(payload, requests)

    result = await GdacsTropicalCycloneAdapter(client=client).find_worldwide_events(
        WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE), now=NOW
    )

    assert result.records[0].source.canonical_url == (
        "https://www.gdacs.org/gdacsapi/api/events/geteventdata?"
        "eventtype=TC&eventid=1001303"
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_empty_result_is_explicit() -> None:
    requests: list[httpx.Request] = []
    client = client_for({"type": "FeatureCollection", "features": []}, requests)

    result = await GdacsTropicalCycloneAdapter(client=client).find_worldwide_events(
        WorldwideDisasterQuery(Hazard.TROPICAL_CYCLONE), now=NOW
    )

    assert result.records == ()
    assert result.issues[0].reason_code == "empty_result"
    await client.aclose()
