import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery, WorldwideDisasterQuery
from disaster_monitor.domain.disaster import Disaster, MeasurementKind
from disaster_monitor.infrastructure.disaster.gdacs_adapter import (
    GdacsFloodAdapter,
    GdacsWildfireAdapter,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


def _fixture(name: str) -> dict[str, object]:
    path = Path(__file__).parents[1] / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _client(payload: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )


@pytest.mark.asyncio
async def test_gdacs_wildfire_retains_source_reported_burned_area() -> None:
    async with _client(_fixture("gdacs_wildfire_search.json")) as client:
        result = await GdacsWildfireAdapter(
            geography=StaticCountryCatalog(), client=client
        ).find_worldwide_events(
            WorldwideDisasterQuery(Disaster.WILDFIRE),
            now=datetime(2026, 8, 24, 12, tzinfo=UTC),
        )

    assert len(result.records) == 1
    burned_area = next(
        (
            item
            for item in result.records[0].measurements
            if item.kind is MeasurementKind.BURNED_AREA
        ),
        None,
    )
    assert burned_area is not None
    assert burned_area.value == 19294
    assert burned_area.unit == "ha"
    assert burned_area.source.source_id == "gdacs-wildfires"


@pytest.mark.asyncio
async def test_gdacs_wildfire_ignores_unused_end_date_field() -> None:
    payload = deepcopy(_fixture("gdacs_wildfire_search.json"))
    properties = payload["features"][0]["properties"]
    assert isinstance(properties, dict)
    properties["todate"] = "not-a-date"

    async with _client(payload) as client:
        result = await GdacsWildfireAdapter(
            geography=StaticCountryCatalog(), client=client
        ).find_worldwide_events(
            WorldwideDisasterQuery(Disaster.WILDFIRE),
            now=datetime(2026, 8, 24, 12, tzinfo=UTC),
        )

    assert len(result.records) == 1


@pytest.mark.asyncio
async def test_gdacs_flood_preserves_reported_end_for_dated_event_selection() -> None:
    feature = deepcopy(_fixture("gdacs_flood_search.json")["features"][0])
    properties = feature["properties"]
    assert isinstance(properties, dict)
    properties.update(
        {
            "eventid": 1104141,
            "iso3": "VNM",
            "affectedcountries": [{"iso3": "VNM"}],
            "country": "Vietnam",
            "fromdate": "2026-09-03T01:00:00",
            "todate": "2026-09-24T01:00:00",
            "iscurrent": "false",
        }
    )
    feature["geometry"]["coordinates"] = [105.8, 18.7]
    country = StaticCountryCatalog().get_by_alpha3("VNM")
    assert country is not None
    query = DisasterQuery(
        Disaster.FLOOD,
        country,
        "dated",
        ("event_overview",),
        date_from=datetime(2026, 9, 24, tzinfo=UTC),
        date_to=datetime(2026, 9, 24, 23, 59, tzinfo=UTC),
    )

    async with _client({"type": "FeatureCollection", "features": [feature]}) as client:
        result = await GdacsFloodAdapter(
            geography=StaticCountryCatalog(), client=client
        ).find_recent_events(query, now=datetime(2026, 9, 27, tzinfo=UTC))

    assert len(result.records) == 1
    assert result.records[0].event_time == datetime(2026, 9, 3, 1, tzinfo=UTC)
    assert result.records[0].event_time_end == datetime(2026, 9, 24, 1, tzinfo=UTC)
