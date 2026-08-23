import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery, WorldwideDisasterQuery
from disaster_monitor.domain.disaster import Disaster, SourceAuthority
from disaster_monitor.infrastructure.disaster.gdacs_adapter import (
    GdacsFloodAdapter,
    GdacsVolcanicEruptionAdapter,
    GdacsWildfireAdapter,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
CATALOG = StaticCountryCatalog()


def fixture(name: str) -> dict[str, object]:
    path = Path(__file__).parents[1] / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def client_for(
    payload: object, requests: list[httpx.Request], *, status: int = 200
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


CASES = (
    (
        GdacsFloodAdapter,
        "gdacs_flood_search.json",
        Disaster.FLOOD,
        "FL",
        "gdacs-floods",
        "gdacs:fl:1104081",
        "GLOFAS",
    ),
    (
        GdacsWildfireAdapter,
        "gdacs_wildfire_search.json",
        Disaster.WILDFIRE,
        "WF",
        "gdacs-wildfires",
        "gdacs:wf:1030410",
        "GWIS",
    ),
    (
        GdacsVolcanicEruptionAdapter,
        "gdacs_volcano_search.json",
        Disaster.VOLCANIC_ERUPTION,
        "VO",
        "gdacs-volcanic-eruptions",
        "gdacs:vo:1000144",
        "TOKYO",
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "adapter_type",
        "fixture_name",
        "disaster",
        "event_type",
        "source_id",
        "event_id",
        "upstream",
    ),
    CASES,
)
async def test_gdacs_secondary_adapters_preserve_event_and_upstream_provenance(
    adapter_type,
    fixture_name: str,
    disaster: Disaster,
    event_type: str,
    source_id: str,
    event_id: str,
    upstream: str,
) -> None:
    requests: list[httpx.Request] = []
    payload = fixture(fixture_name)
    client = client_for(payload, requests)
    adapter = adapter_type(geography=CATALOG, client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(disaster, time_window_days=30, limit=7), now=NOW
    )

    assert result.issues == ()
    event = result.records[0]
    assert event.event_id == event_id
    assert event.disaster is disaster
    assert event.source.source_id == source_id
    assert event.source.authority is SourceAuthority.SECONDARY
    assert upstream in event.source.publisher
    assert event.source.canonical_url.startswith("https://www.gdacs.org/")
    assert event.provider_ids[0] == event_id
    assert event.provider_ids[1].startswith(f"{event_id}:")
    assert any(item.startswith("glide:") for item in event.provider_ids)
    params = dict(requests[0].url.params.multi_items())
    assert params == {
        "eventlist": event_type,
        "fromDate": (NOW - timedelta(days=30)).isoformat(),
        "toDate": NOW.isoformat(),
        "pageSize": "100",
        "pageNumber": "1",
    }

    feature = payload["features"][0]  # type: ignore[index]
    feature["properties"]["iso3"] = "JPN"  # type: ignore[index]
    feature["properties"]["affectedcountries"] = [{"iso3": "JPN"}]  # type: ignore[index]
    feature["geometry"]["coordinates"] = [139.0, 35.0]  # type: ignore[index]
    country = CATALOG.get_by_alpha3("JPN")
    assert country is not None
    country_result = await adapter.find_recent_events(
        DisasterQuery(disaster, country, "recent", ("latest",)), now=NOW
    )
    assert country_result.records[0].country.alpha3_code == "JPN"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_type", "fixture_name", "disaster"),
    tuple((case[0], case[1], case[2]) for case in CASES),
)
async def test_gdacs_secondary_adapters_skip_wrong_event_type_and_bad_sibling(
    adapter_type, fixture_name: str, disaster: Disaster
) -> None:
    payload = fixture(fixture_name)
    payload["features"].append({})  # type: ignore[union-attr]
    client = client_for(payload, [])

    result = await adapter_type(geography=CATALOG, client=client).find_worldwide_events(
        WorldwideDisasterQuery(disaster), now=NOW
    )

    assert len(result.records) == 1
    assert result.issues[0].reason_code == "invalid_record"
    wrong = await adapter_type(geography=CATALOG, client=client).find_worldwide_events(
        WorldwideDisasterQuery(Disaster.EARTHQUAKE), now=NOW
    )
    assert wrong.records == ()
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_country_query_preserves_explicit_date_bounds() -> None:
    requests: list[httpx.Request] = []
    client = client_for(fixture("gdacs_volcano_search.json"), requests)
    country = CATALOG.get_by_alpha3("JPN")
    assert country is not None
    date_from = datetime(2026, 7, 15, 15, tzinfo=UTC)
    date_to = datetime(2026, 7, 16, 15, tzinfo=UTC)
    query = DisasterQuery(
        Disaster.VOLCANIC_ERUPTION,
        country,
        "on 2026-07-16",
        ("latest",),
        date_from=date_from,
        date_to=date_to,
    )

    await GdacsVolcanicEruptionAdapter(
        geography=CATALOG, client=client
    ).find_recent_events(query, now=NOW)

    params = dict(requests[0].url.params.multi_items())
    assert params["fromDate"] == date_from.isoformat()
    assert params["toDate"] == date_to.isoformat()
    await client.aclose()
