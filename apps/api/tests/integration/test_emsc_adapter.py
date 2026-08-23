import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.disaster import (
    DisasterQuery,
    WorldwideDisasterQuery,
    WorldwideSelectionIntent,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    EventGeographyStatus,
    MeasurementKind,
    SourceAuthority,
)
from disaster_monitor.infrastructure.disaster.emsc_adapter import (
    EmscEarthquakeAdapter,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
assert JAPAN is not None
FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "emsc_earthquakes.json"


def emsc_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def client_for(
    payload: object,
    requests: list[httpx.Request],
    *,
    status: int = 200,
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode(),
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def country_query() -> DisasterQuery:
    return DisasterQuery(
        Disaster.EARTHQUAKE,
        JAPAN,
        "recent",
        ("latest developments",),
        time_window_days=7,
    )


@pytest.mark.asyncio
async def test_emsc_translates_scientific_event_with_snapshot_provenance() -> None:
    requests: list[httpx.Request] = []
    snapshots: list[object] = []

    async def record_snapshot(payload: object) -> object:
        snapshots.append(payload)
        return SimpleNamespace(snapshot_id="snapshot:emsc-fixture")

    client = client_for(emsc_payload(), requests)
    adapter = EmscEarthquakeAdapter(
        geography=CATALOG,
        client=client,
        snapshot_recorder=record_snapshot,
    )

    result = await adapter.find_recent_events(country_query(), now=NOW)

    assert result.issues == ()
    event = result.records[0]
    assert event.event_id == "emsc:20260818_0000100"
    assert event.provider_ids == (
        "emsc:20260818_0000100",
        "emsc-catalog:EMSC-RTS:2049001",
    )
    assert event.location == "NEAR EAST COAST OF HONSHU, JAPAN"
    assert event.country == JAPAN
    assert event.geography_status is EventGeographyStatus.IN_COUNTRY
    assert event.source.source_id == "emsc-earthquakes"
    assert event.source.authority is SourceAuthority.SCIENTIFIC_AUTHORITY
    assert event.source.canonical_url == (
        "https://www.seismicportal.eu/eventdetails.html?unid=20260818_0000100"
    )
    assert event.source.published_at == datetime(2026, 8, 18, 11, 30, tzinfo=UTC)
    assert event.source.updated_at == datetime(2026, 8, 18, 11, 35, tzinfo=UTC)
    assert event.source.snapshot_id == "snapshot:emsc-fixture"
    assert event.geometry is not None
    assert event.geometry.coordinates[0].latitude == 36.0
    assert event.geometry.coordinates[0].longitude == 140.0
    assert [(item.kind, item.value, item.unit) for item in event.measurements] == [
        (MeasurementKind.MAGNITUDE, 5.8, None),
        (MeasurementKind.DEPTH, 20.0, "km"),
    ]
    assert len(snapshots) == 1
    assert snapshots[0].rights_id == "emsc-fdsn-event-cc-by-4.0"
    await client.aclose()


@pytest.mark.asyncio
async def test_emsc_country_query_is_bounded_and_country_validated() -> None:
    requests: list[httpx.Request] = []
    payload = emsc_payload()
    client = client_for(payload, requests)
    adapter = EmscEarthquakeAdapter(geography=CATALOG, client=client)

    result = await adapter.find_recent_events(country_query(), now=NOW)
    params = dict(requests[0].url.params.multi_items())

    assert params == {
        "format": "json",
        "catalog": "EMSC-RTS",
        "starttime": (NOW - timedelta(days=7)).isoformat(),
        "endtime": NOW.isoformat(),
        "minlatitude": "20.0",
        "maxlatitude": "46.0",
        "minlongitude": "122.0",
        "maxlongitude": "154.0",
        "minmagnitude": "4.5",
        "orderby": "magnitude",
        "limit": "50",
    }
    assert len(result.records) == 1

    feature = payload["features"][0]  # type: ignore[index]
    feature["geometry"]["coordinates"] = [123.0, 21.0, 20.0]  # type: ignore[index]
    mismatch_client = client_for(payload, [])
    mismatch = await EmscEarthquakeAdapter(
        geography=CATALOG, client=mismatch_client
    ).find_recent_events(country_query(), now=NOW)
    assert mismatch.records == ()
    assert mismatch.issues[0].reason_code == "country_mismatch"
    await client.aclose()
    await mismatch_client.aclose()


@pytest.mark.asyncio
async def test_emsc_worldwide_query_preserves_scope_and_selection_intent() -> None:
    requests: list[httpx.Request] = []
    client = client_for(emsc_payload(), requests)
    adapter = EmscEarthquakeAdapter(geography=CATALOG, client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(
            Disaster.EARTHQUAKE,
            time_window_days=3,
            limit=7,
            selection_intent=WorldwideSelectionIntent.STRONGEST,
        ),
        now=NOW,
    )
    params = dict(requests[0].url.params.multi_items())

    assert params == {
        "format": "json",
        "catalog": "EMSC-RTS",
        "starttime": (NOW - timedelta(days=3)).isoformat(),
        "endtime": NOW.isoformat(),
        "minmagnitude": "4.5",
        "orderby": "magnitude",
        "limit": "7",
    }
    assert result.records[0].event_id == "emsc:20260818_0000100"
    assert not hasattr(result.records[0], "country")
    await client.aclose()


@pytest.mark.asyncio
async def test_emsc_skips_malformed_sibling_and_rejects_invalid_schema() -> None:
    payload = emsc_payload()
    payload["features"].append({})  # type: ignore[union-attr]
    client = client_for(payload, [])
    result = await EmscEarthquakeAdapter(
        geography=CATALOG, client=client
    ).find_recent_events(country_query(), now=NOW)
    assert [item.event_id for item in result.records] == ["emsc:20260818_0000100"]
    assert result.issues[0].reason_code == "invalid_record"
    await client.aclose()

    invalid_client = client_for({"not": "geojson"}, [])
    with pytest.raises(DisasterProviderResponseError):
        await EmscEarthquakeAdapter(
            geography=CATALOG, client=invalid_client
        ).find_recent_events(country_query(), now=NOW)
    await invalid_client.aclose()


@pytest.mark.asyncio
async def test_emsc_empty_no_content_response_is_a_no_match() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, content=b"", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await EmscEarthquakeAdapter(
        geography=CATALOG, client=client
    ).find_recent_events(country_query(), now=NOW)

    assert result.records == ()
    assert result.issues[0].reason_code == "empty_result"
    assert len(requests) == 1
    await client.aclose()
