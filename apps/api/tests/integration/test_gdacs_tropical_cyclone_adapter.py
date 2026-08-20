import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.disaster import (
    DisasterQuery,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.services.worldwide_disaster_policy import (
    DefaultWorldwideDisasterPolicy,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    MeasurementKind,
    SourceAuthority,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.gdacs_adapter import (
    GdacsTropicalCycloneAdapter,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
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


def country_query(country_code: str) -> DisasterQuery:
    country = StaticCountryCatalog().get_by_alpha3(country_code)
    assert country is not None
    return DisasterQuery(Disaster.TROPICAL_CYCLONE, country, "recent", ("latest",))


def country_payload(
    *,
    iso3: object,
    coordinates: list[float],
    affectedcountries: object = None,
) -> dict[str, object]:
    payload = gdacs_payload()
    features = payload["features"]
    assert isinstance(features, list)
    feature = features[0]
    assert isinstance(feature, dict)
    properties = feature["properties"]
    assert isinstance(properties, dict)
    properties["iso3"] = iso3
    if affectedcountries is not None:
        properties["affectedcountries"] = affectedcountries
    properties["country"] = "Japan"
    geometry = feature["geometry"]
    assert isinstance(geometry, dict)
    geometry["coordinates"] = coordinates
    payload["features"] = [feature]
    return payload


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
        WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE), now=NOW
    )

    event = result.records[0]
    assert [item.event_id for item in result.records] == [
        "gdacs:tc:1001303",
        "gdacs:tc:1001304",
    ]
    assert [item.event_time for item in result.records] == [
        datetime(2026, 8, 12, 15, tzinfo=UTC),
        datetime(2026, 8, 13, 3, tzinfo=UTC),
    ]
    latest = DefaultWorldwideDisasterPolicy().select(
        result.records, WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE)
    )
    assert latest is not None
    assert latest.event_id == "gdacs:tc:1001304"
    assert latest.event_time == datetime(2026, 8, 13, 3, tzinfo=UTC)
    assert event.disaster is Disaster.TROPICAL_CYCLONE
    assert event.location == "United States"
    assert event.event_time == datetime(2026, 8, 12, 15, tzinfo=UTC)
    assert event.provider_ids == ("gdacs:tc:1001303", "gdacs:tc:1001303:24")
    assert event.source.source_id == "gdacs-tropical-cyclones"
    assert event.source.canonical_url.startswith("https://www.gdacs.org/")
    assert event.source.published_at is None
    assert event.source.updated_at == datetime(2026, 8, 18, 11, 37, 9, tzinfo=UTC)
    assert event.source.authority is SourceAuthority.SECONDARY
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
    assert snapshots[0].rights_id == "gdacs-terms-of-use"
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_query_is_tropical_cyclone_only_and_bounded() -> None:
    requests: list[httpx.Request] = []
    client = client_for(gdacs_payload(), requests)
    adapter = GdacsTropicalCycloneAdapter(client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE, time_window_days=5, limit=7),
        now=NOW,
    )
    params = dict(requests[0].url.params.multi_items())

    assert params == {
        "eventlist": "TC",
        "fromDate": (NOW - timedelta(days=5)).isoformat(),
        "toDate": NOW.isoformat(),
        "pageSize": "100",
        "pageNumber": "1",
    }
    assert result.records

    wrong_disaster = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.EARTHQUAKE), now=NOW
    )
    assert wrong_disaster.records == ()
    assert len(requests) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_country_query_accepts_primary_iso3_and_projects_japan_event() -> (
    None
):
    requests: list[httpx.Request] = []
    client = client_for(
        country_payload(iso3="JPN", coordinates=[139.0, 35.0]), requests
    )
    catalog = StaticCountryCatalog()
    adapter = GdacsTropicalCycloneAdapter(client=client, geography=catalog)

    result = await adapter.find_recent_events(country_query("JPN"), now=NOW)

    assert len(result.records) == 1
    event = result.records[0]
    assert isinstance(event, DisasterEvent)
    assert event.country.alpha3_code == "JPN"
    assert event.geography_status is EventGeographyStatus.IN_COUNTRY
    assert event.geometry is not None
    assert len(requests) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_country_query_rejects_unrelated_country_evidence() -> None:
    requests: list[httpx.Request] = []
    client = client_for(
        country_payload(
            iso3="KOR",
            coordinates=[139.0, 35.0],
            affectedcountries=[{"iso3": "USA", "countryname": "United States"}],
        ),
        requests,
    )
    adapter = GdacsTropicalCycloneAdapter(
        client=client, geography=StaticCountryCatalog()
    )

    result = await adapter.find_recent_events(country_query("JPN"), now=NOW)

    assert result.records == ()
    assert result.issues == ()
    assert len(requests) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_country_query_accepts_affected_country_iso3() -> None:
    requests: list[httpx.Request] = []
    client = client_for(
        country_payload(
            iso3="MHL",
            coordinates=[160.0, 20.0],
            affectedcountries=[{"iso3": "JPN", "countryname": "Japan"}],
        ),
        requests,
    )
    adapter = GdacsTropicalCycloneAdapter(
        client=client, geography=StaticCountryCatalog()
    )

    result = await adapter.find_recent_events(country_query("JPN"), now=NOW)

    assert len(result.records) == 1
    assert result.records[0].country.alpha3_code == "JPN"
    assert result.issues == ()
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_worldwide_query_keeps_multicountry_event_worldwide() -> None:
    requests: list[httpx.Request] = []
    client = client_for(
        country_payload(
            iso3="MHL",
            coordinates=[160.0, 20.0],
            affectedcountries=[{"iso3": "JPN", "countryname": "Japan"}],
        ),
        requests,
    )
    adapter = GdacsTropicalCycloneAdapter(client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE), now=NOW
    )

    assert len(result.records) == 1
    assert isinstance(result.records[0], WorldwideDisasterEvent)
    assert not hasattr(result.records[0], "country")
    assert result.issues == ()
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "country_evidence",
    [
        {"iso3": "", "affectedcountries": []},
        {"iso3": None, "affectedcountries": [{"countryname": "Japan"}]},
        {"iso3": "KOR", "affectedcountries": [{"iso2": "JP"}]},
        {"iso3": "KOR", "affectedcountries": "JPN"},
    ],
)
async def test_gdacs_country_query_fails_closed_without_sufficient_country_evidence(
    country_evidence: dict[str, object],
) -> None:
    requests: list[httpx.Request] = []
    client = client_for(
        country_payload(
            iso3=country_evidence["iso3"],
            coordinates=[139.0, 35.0],
            affectedcountries=country_evidence["affectedcountries"],
        ),
        requests,
    )
    adapter = GdacsTropicalCycloneAdapter(
        client=client, geography=StaticCountryCatalog()
    )

    result = await adapter.find_recent_events(country_query("JPN"), now=NOW)

    assert result.records == ()
    assert result.issues == ()
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_country_query_marks_explicit_japan_offshore_association() -> None:
    requests: list[httpx.Request] = []
    client = client_for(
        country_payload(iso3="JPN", coordinates=[160.0, 20.0]), requests
    )
    adapter = GdacsTropicalCycloneAdapter(
        client=client, geography=StaticCountryCatalog()
    )

    result = await adapter.find_recent_events(country_query("JPN"), now=NOW)

    assert len(result.records) == 1
    assert result.records[0].geography_status is (
        EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_country_query_fails_closed_without_country_projection() -> None:
    requests: list[httpx.Request] = []
    client = client_for(
        country_payload(iso3="JPN", coordinates=[139.0, 35.0]), requests
    )
    adapter = GdacsTropicalCycloneAdapter(client=client)

    result = await adapter.find_recent_events(country_query("JPN"), now=NOW)

    assert result.records == ()
    assert result.issues[0].reason_code == "country_projection_unusable"
    assert requests == []
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
        WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE), now=NOW
    )

    assert len(result.records) == 2
    assert [issue.reason_code for issue in result.issues] == ["invalid_record"]
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_does_not_fallback_to_end_time_without_onset() -> None:
    payload = gdacs_payload()
    features = payload["features"]
    assert isinstance(features, list)
    first = features[0]
    assert isinstance(first, dict)
    properties = first["properties"]
    assert isinstance(properties, dict)
    properties["fromdate"] = None
    requests: list[httpx.Request] = []
    client = client_for(payload, requests)

    result = await GdacsTropicalCycloneAdapter(client=client).find_worldwide_events(
        WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE), now=NOW
    )

    assert [event.event_id for event in result.records] == ["gdacs:tc:1001304"]
    assert [issue.reason_code for issue in result.issues] == ["invalid_record"]
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_rejects_malformed_top_level_response() -> None:
    requests: list[httpx.Request] = []
    client = client_for({"type": "FeatureCollection"}, requests)

    with pytest.raises(DisasterProviderResponseError):
        await GdacsTropicalCycloneAdapter(client=client).find_worldwide_events(
            WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE), now=NOW
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
        WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE), now=NOW
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
        WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE), now=NOW
    )

    assert result.records == ()
    assert result.issues[0].reason_code == "empty_result"
    await client.aclose()


@pytest.mark.asyncio
async def test_gdacs_no_content_is_a_successful_empty_result() -> None:
    requests: list[httpx.Request] = []
    client = client_for(b"", requests, status=204, content_type="")

    result = await GdacsTropicalCycloneAdapter(client=client).find_worldwide_events(
        WorldwideDisasterQuery(Disaster.TROPICAL_CYCLONE), now=NOW
    )

    assert result.records == ()
    assert [issue.reason_code for issue in result.issues] == ["empty_result"]
    await client.aclose()
