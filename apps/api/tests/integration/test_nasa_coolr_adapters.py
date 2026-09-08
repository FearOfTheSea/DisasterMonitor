import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery, WorldwideDisasterQuery
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    MeasurementKind,
    SourceAuthority,
)
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
)
from disaster_monitor.infrastructure.disaster.nasa_coolr_adapter import (
    NasaCoolrLandslideAdapter,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def query(disaster: Disaster, country_code: str = "JPN") -> DisasterQuery:
    country = StaticCountryCatalog().get_by_alpha3(country_code)
    assert country is not None
    return DisasterQuery(disaster, country, "recent", ("latest",), time_window_days=5)


def client_for(
    payload: object,
    requests: list[httpx.Request],
    *,
    status: int = 200,
    content_type: str = "application/json",
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers={"content-type": content_type},
            content=json.dumps(payload).encode(),
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_coolr_translates_report_and_requests_exact_bounded_fields() -> None:
    requests: list[httpx.Request] = []
    client = client_for(load_fixture("nasa_coolr_landslides.json"), requests)
    adapter = NasaCoolrLandslideAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(query(Disaster.LANDSLIDE), now=NOW)

    assert len(result.records) == 1
    event = result.records[0]
    assert isinstance(event, DisasterEvent)
    assert event.event_id == "coolr:COOLR_FIXTURE_1"
    assert event.provider_ids == ("coolr:COOLR_FIXTURE_1", "GLC:GLC-101")
    assert event.location == "Mountain road near Tokyo"
    assert event.event_time == datetime(2026, 8, 17, 10, tzinfo=UTC)
    assert event.source.updated_at == datetime(2026, 8, 18, 11, tzinfo=UTC)
    assert event.source.authority is SourceAuthority.SECONDARY
    assert event.source.source_id == "nasa-coolr-landslides"
    assert event.source.canonical_url.startswith(
        "https://gis.earthdata.nasa.gov/gis05/"
    )
    assert event.geometry is not None
    assert event.geometry.coordinates[0].latitude == 35.0
    assert event.geometry.coordinates[0].longitude == 139.0
    severity = event.measurement(MeasurementKind.SEVERITY)
    assert severity is not None
    assert severity.value == "large"
    assert all(
        item.kind is not MeasurementKind.MAGNITUDE for item in event.measurements
    )
    params = dict(requests[0].url.params.multi_items())
    assert requests[0].url.path.startswith("/gis05/")
    assert params["f"] == "json"
    assert params["returnGeometry"] == "true"
    assert params["outSR"] == "4326"
    assert params["orderByFields"] == "event_date DESC"
    assert params["resultRecordCount"] == "50"
    assert "event_import_source IN ('GLC', 'LRC')" in params["where"]
    assert set(params["outFields"].split(",")) == {
        "objectid",
        "event_id",
        "event_date",
        "event_time",
        "event_title",
        "location_description",
        "landslide_category",
        "landslide_trigger",
        "landslide_size",
        "event_import_source",
        "event_import_id",
        "latitude",
        "longitude",
        "country_name",
        "country_code",
        "admin_division_name",
        "source_name",
        "submitted_date",
        "last_edited_date",
    }
    envelope = json.loads(params["geometry"])
    assert envelope["spatialReference"] == {"wkid": 4326}
    assert params["geometryType"] == "esriGeometryEnvelope"
    assert params["spatialRel"] == "esriSpatialRelIntersects"
    await client.aclose()


@pytest.mark.asyncio
async def test_coolr_source_name_is_not_event_location() -> None:
    payload = load_fixture("nasa_coolr_landslides.json")
    features = payload["features"]
    assert isinstance(features, list)
    feature = features[0]
    assert isinstance(feature, dict)
    attributes = feature["attributes"]
    assert isinstance(attributes, dict)
    for field in (
        "location_description",
        "event_title",
        "admin_division_name",
        "country_name",
        "country_code",
    ):
        attributes[field] = None
    attributes["source_name"] = "Example News Agency"
    client = client_for(payload, [])
    result = await NasaCoolrLandslideAdapter(client=client).find_worldwide_events(
        WorldwideDisasterQuery(Disaster.LANDSLIDE), now=NOW
    )

    assert result.records == ()
    assert any(issue.reason_code == "invalid_record" for issue in result.issues)
    assert "Example News Agency" not in str(result.records)
    await client.aclose()


@pytest.mark.asyncio
async def test_coolr_whitespace_only_location_fields_are_not_admitted() -> None:
    payload = load_fixture("nasa_coolr_landslides.json")
    features = payload["features"]
    assert isinstance(features, list)
    feature = features[0]
    assert isinstance(feature, dict)
    attributes = feature["attributes"]
    assert isinstance(attributes, dict)
    for field in (
        "location_description",
        "event_title",
        "admin_division_name",
        "country_name",
        "country_code",
    ):
        attributes[field] = " \t "
    attributes["source_name"] = "Example News Agency"
    client = client_for(payload, [])
    result = await NasaCoolrLandslideAdapter(client=client).find_worldwide_events(
        WorldwideDisasterQuery(Disaster.LANDSLIDE), now=NOW
    )

    assert result.records == ()
    assert any(issue.reason_code == "invalid_record" for issue in result.issues)
    await client.aclose()


@pytest.mark.asyncio
async def test_coolr_valid_sibling_survives_rejected_no_location_feature() -> None:
    payload = load_fixture("nasa_coolr_landslides.json")
    features = payload["features"]
    assert isinstance(features, list)
    invalid = copy.deepcopy(features[0])
    assert isinstance(invalid, dict)
    invalid_attributes = invalid["attributes"]
    assert isinstance(invalid_attributes, dict)
    for field in (
        "location_description",
        "event_title",
        "admin_division_name",
        "country_name",
        "country_code",
    ):
        invalid_attributes[field] = None
    invalid_attributes["source_name"] = "Example News Agency"
    payload["features"] = [invalid, features[0]]
    client = client_for(payload, [])
    result = await NasaCoolrLandslideAdapter(client=client).find_worldwide_events(
        WorldwideDisasterQuery(Disaster.LANDSLIDE), now=NOW
    )

    assert [item.event_id for item in result.records] == ["coolr:COOLR_FIXTURE_1"]
    assert result.records[0].location != "Example News Agency"
    assert any(issue.reason_code == "invalid_record" for issue in result.issues)
    await client.aclose()


@pytest.mark.asyncio
async def test_coolr_malformed_sibling_insertion_does_not_change_valid_record() -> None:
    payload = load_fixture("nasa_coolr_landslides.json")
    features = payload["features"]
    assert isinstance(features, list)
    valid = copy.deepcopy(features[0])
    malformed = {}
    results = []
    for ordered_features in ([valid, malformed], [malformed, valid]):
        client = client_for({"features": copy.deepcopy(ordered_features)}, [])
        results.append(
            await NasaCoolrLandslideAdapter(client=client).find_worldwide_events(
                WorldwideDisasterQuery(Disaster.LANDSLIDE), now=NOW
            )
        )
        await client.aclose()

    assert results[0].records == results[1].records
    assert all(issue.reason_code == "invalid_record" for issue in results[0].issues)
    assert all(issue.reason_code == "invalid_record" for issue in results[1].issues)


@pytest.mark.asyncio
async def test_coolr_duplicate_identity_is_deduplicated_or_rejected() -> None:
    payload = load_fixture("nasa_coolr_landslides.json")
    features = payload["features"]
    assert isinstance(features, list)
    valid = copy.deepcopy(features[0])
    conflicting = copy.deepcopy(features[0])
    assert isinstance(conflicting, dict)
    conflicting_attributes = conflicting["attributes"]
    assert isinstance(conflicting_attributes, dict)
    conflicting_attributes["location_description"] = "Conflicting duplicate"
    for duplicate_features, expected_count, expected_issue in (
        ([valid, copy.deepcopy(valid)], 1, None),
        ([valid, conflicting], 0, "duplicate_identity"),
    ):
        client = client_for({"features": duplicate_features}, [])
        result = await NasaCoolrLandslideAdapter(client=client).find_worldwide_events(
            WorldwideDisasterQuery(Disaster.LANDSLIDE), now=NOW
        )
        assert len(result.records) == expected_count
        if expected_issue is not None:
            assert any(issue.reason_code == expected_issue for issue in result.issues)
        await client.aclose()


@pytest.mark.asyncio
async def test_coolr_worldwide_omits_country_geometry_and_rejects_future_sources() -> (
    None
):
    requests: list[httpx.Request] = []
    client = client_for(load_fixture("nasa_coolr_landslides.json"), requests)
    adapter = NasaCoolrLandslideAdapter(client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.LANDSLIDE, time_window_days=365, limit=999),
        now=NOW,
    )

    params = dict(requests[0].url.params.multi_items())
    assert "geometry" not in params
    assert "geometryType" not in params
    assert "spatialRel" not in params
    assert len(result.records) == 1
    assert any(
        issue.reason_code == "unsupported_import_source" for issue in result.issues
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_coolr_rejects_conflicting_coordinates_and_polygon_mismatch() -> None:
    payload = load_fixture("nasa_coolr_landslides.json")
    features = payload["features"]
    assert isinstance(features, list)
    valid = features[0]
    assert isinstance(valid, dict)
    attributes = valid["attributes"]
    assert isinstance(attributes, dict)
    attributes["event_id"] = "COOLR_OUTSIDE_POLYGON"
    attributes["latitude"] = 40.0
    attributes["longitude"] = 124.0
    geometry = valid["geometry"]
    assert isinstance(geometry, dict)
    geometry["x"] = 124.0
    geometry["y"] = 40.0
    requests: list[httpx.Request] = []
    client = client_for(payload, requests)
    adapter = NasaCoolrLandslideAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(query(Disaster.LANDSLIDE), now=NOW)

    assert result.records == ()
    assert any(issue.reason_code == "country_mismatch" for issue in result.issues)
    assert any(issue.reason_code == "invalid_record" for issue in result.issues)
    await client.aclose()


@pytest.mark.asyncio
async def test_coolr_uses_objectid_fallback_and_keeps_http_failure_typed() -> None:
    payload = load_fixture("nasa_coolr_landslides.json")
    features = payload["features"]
    assert isinstance(features, list)
    fallback = copy.deepcopy(features[0])
    assert isinstance(fallback, dict)
    fallback_attributes = fallback["attributes"]
    assert isinstance(fallback_attributes, dict)
    fallback_attributes["event_id"] = None
    fallback_attributes["objectid"] = 404
    payload["features"] = [fallback]
    requests: list[httpx.Request] = []
    client = client_for(payload, requests)
    adapter = NasaCoolrLandslideAdapter(client=client)
    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.LANDSLIDE), now=NOW
    )
    assert result.records[0].event_id == "coolr:objectid:404"
    await client.aclose()

    attempts = 0

    def failing_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            503,
            headers={"content-type": "application/json"},
            content=b"{}",
            request=request,
        )

    failing_client = httpx.AsyncClient(transport=httpx.MockTransport(failing_handler))
    failing_adapter = NasaCoolrLandslideAdapter(client=failing_client)
    batch = await CompositeDisasterEventProvider((failing_adapter,)).find_recent_events(
        query(Disaster.LANDSLIDE), now=NOW
    )
    assert batch.records == ()
    assert batch.issues[0].reason_code == "http_server_error"
    assert attempts == 2
    await failing_client.aclose()
