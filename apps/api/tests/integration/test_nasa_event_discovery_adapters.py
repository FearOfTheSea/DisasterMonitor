import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery, WorldwideDisasterQuery
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventGeometryKind,
    MeasurementKind,
    SourceAuthority,
)
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
)
from disaster_monitor.infrastructure.disaster.nasa_coolr_adapter import (
    NasaCoolrLandslideAdapter,
)
from disaster_monitor.infrastructure.disaster.nasa_eonet_adapter import (
    NasaEonetWildfireAdapter,
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


def _eonet_payload_with_geometry(
    geometry: list[dict[str, object]],
    *,
    event_id: str = "EONET_LONG_RUNNING",
) -> dict[str, object]:
    event = copy.deepcopy(load_fixture("nasa_eonet_wildfires.json")["events"][0])
    assert isinstance(event, dict)
    event["id"] = event_id
    event["geometry"] = geometry
    return {"events": [event]}


def _eonet_point(date: str, longitude: float = 140.0, latitude: float = 36.0):
    return {
        "date": date,
        "type": "Point",
        "coordinates": [longitude, latitude],
        "magnitudeValue": 2500,
        "magnitudeUnit": "acres",
    }


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
async def test_eonet_translates_event_geometry_measurement_and_source_timestamps() -> (
    None
):
    requests: list[httpx.Request] = []
    client = client_for(load_fixture("nasa_eonet_wildfires.json"), requests)
    adapter = NasaEonetWildfireAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(query(Disaster.WILDFIRE), now=NOW)

    assert len(result.records) == 1
    event = result.records[0]
    assert isinstance(event, DisasterEvent)
    assert event.event_id == "eonet:EONET_FIXTURE_1"
    assert event.provider_ids == ("eonet:EONET_FIXTURE_1", "IRWIN")
    assert event.event_time == datetime(2026, 8, 15, 10, tzinfo=UTC)
    assert event.source.published_at == event.event_time
    assert event.source.updated_at == datetime(2026, 8, 17, 10, tzinfo=UTC)
    assert event.source.authority is SourceAuthority.SECONDARY
    assert event.source.source_id == "nasa-eonet-wildfires"
    assert event.source.canonical_url == (
        "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_FIXTURE_1"
    )
    assert event.geometry is not None
    assert event.geometry.kind is EventGeometryKind.POINT
    assert event.geometry.coordinates[0].latitude == 36.0
    assert event.geometry.coordinates[0].longitude == 140.0
    measurement = event.measurement(MeasurementKind.MAGNITUDE)
    assert measurement is not None
    assert measurement.value == 2500
    assert measurement.unit == "acres"
    assert requests[0].url.host == "eonet.gsfc.nasa.gov"
    await client.aclose()


@pytest.mark.asyncio
async def test_eonet_country_and_worldwide_queries_are_bounded_and_scoped() -> None:
    requests: list[httpx.Request] = []
    client = client_for(load_fixture("nasa_eonet_wildfires.json"), requests)
    adapter = NasaEonetWildfireAdapter(client=client, geography=StaticCountryCatalog())

    await adapter.find_recent_events(query(Disaster.WILDFIRE), now=NOW)
    await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.WILDFIRE, time_window_days=365, limit=999),
        now=NOW,
    )

    country_params = dict(requests[0].url.params.multi_items())
    assert country_params == {
        "category": "wildfires",
        "status": "all",
        "start": "2026-08-13",
        "end": "2026-08-18",
        "limit": "50",
        "bbox": "122.0,46.0,154.0,20.0",
    }
    worldwide_params = dict(requests[1].url.params.multi_items())
    assert worldwide_params == {
        "category": "wildfires",
        "status": "all",
        "start": "2026-07-19",
        "end": "2026-08-18",
        "limit": "50",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_eonet_honors_small_worldwide_limit_without_exceeding_provider_max() -> (
    None
):
    requests: list[httpx.Request] = []
    client = client_for(load_fixture("nasa_eonet_wildfires.json"), requests)
    adapter = NasaEonetWildfireAdapter(client=client)

    await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.WILDFIRE, limit=1), now=NOW
    )

    params = dict(requests[0].url.params.multi_items())
    assert params["limit"] == "1"
    await client.aclose()


@pytest.mark.asyncio
async def test_eonet_long_running_event_keeps_source_start_outside_query_window() -> (
    None
):
    payload = _eonet_payload_with_geometry(
        [
            _eonet_point("2026-08-10T10:00:00Z"),
            _eonet_point("2026-08-15T10:00:00Z", 141.0, 37.0),
            _eonet_point("2026-08-17T10:00:00Z", 142.0, 38.0),
        ]
    )
    client = client_for(payload, [])
    result = await NasaEonetWildfireAdapter(
        client=client, geography=StaticCountryCatalog()
    ).find_recent_events(query(Disaster.WILDFIRE), now=NOW)

    assert len(result.records) == 1
    event = result.records[0]
    assert event.event_time == datetime(2026, 8, 10, 10, tzinfo=UTC)
    assert event.source.updated_at == datetime(2026, 8, 17, 10, tzinfo=UTC)
    assert event.geometry is not None
    assert event.geometry.coordinates[0].longitude == 142.0
    await client.aclose()


@pytest.mark.asyncio
async def test_eonet_historical_only_event_is_not_admitted_as_current() -> None:
    payload = _eonet_payload_with_geometry([_eonet_point("2026-08-10T10:00:00Z")])
    client = client_for(payload, [])
    result = await NasaEonetWildfireAdapter(
        client=client, geography=StaticCountryCatalog()
    ).find_recent_events(query(Disaster.WILDFIRE), now=NOW)

    assert result.records == ()
    assert any(issue.reason_code == "invalid_record" for issue in result.issues)
    await client.aclose()


@pytest.mark.asyncio
async def test_eonet_malformed_middle_geometry_preserves_event() -> None:
    payload = _eonet_payload_with_geometry(
        [
            _eonet_point("2026-08-10T10:00:00Z"),
            {"date": "not-a-date", "type": "Point", "coordinates": [140, 36]},
            _eonet_point("2026-08-17T10:00:00Z", 141.0, 37.0),
        ]
    )
    client = client_for(payload, [])
    result = await NasaEonetWildfireAdapter(
        client=client, geography=StaticCountryCatalog()
    ).find_recent_events(query(Disaster.WILDFIRE), now=NOW)

    assert len(result.records) == 1
    assert result.records[0].event_time == datetime(2026, 8, 10, 10, tzinfo=UTC)
    assert any(issue.reason_code == "invalid_geometry" for issue in result.issues)
    await client.aclose()


@pytest.mark.asyncio
async def test_eonet_geometry_order_and_inclusive_boundaries_are_deterministic() -> (
    None
):
    start = datetime(2026, 8, 13, tzinfo=UTC)
    end = datetime(2026, 8, 18, tzinfo=UTC)
    geometry = [
        _eonet_point(start.isoformat().replace("+00:00", "Z")),
        _eonet_point(end.isoformat().replace("+00:00", "Z"), 141.0, 37.0),
    ]
    bounded = replace(query(Disaster.WILDFIRE), date_from=start, date_to=end)

    forward_client = client_for(_eonet_payload_with_geometry(geometry), [])
    reverse_client = client_for(
        _eonet_payload_with_geometry(list(reversed(geometry))), []
    )
    forward = await NasaEonetWildfireAdapter(
        client=forward_client, geography=StaticCountryCatalog()
    ).find_recent_events(bounded, now=NOW)
    reverse = await NasaEonetWildfireAdapter(
        client=reverse_client, geography=StaticCountryCatalog()
    ).find_recent_events(bounded, now=NOW)

    assert len(forward.records) == len(reverse.records) == 1
    assert forward.records[0] == reverse.records[0]
    assert forward.records[0].event_time == start
    assert forward.records[0].source.updated_at == end
    await forward_client.aclose()
    await reverse_client.aclose()


@pytest.mark.asyncio
async def test_eonet_malformed_sibling_does_not_change_valid_normalization() -> None:
    valid = copy.deepcopy(load_fixture("nasa_eonet_wildfires.json")["events"][0])
    assert isinstance(valid, dict)
    malformed = {"id": "bad"}
    results = []
    for events in ([malformed, valid], [valid, malformed]):
        client = client_for({"events": copy.deepcopy(events)}, [])
        results.append(
            await NasaEonetWildfireAdapter(client=client).find_worldwide_events(
                WorldwideDisasterQuery(Disaster.WILDFIRE), now=NOW
            )
        )
        await client.aclose()

    assert results[0].records == results[1].records
    assert all(issue.reason_code == "invalid_record" for issue in results[0].issues)
    assert all(issue.reason_code == "invalid_record" for issue in results[1].issues)


@pytest.mark.asyncio
async def test_eonet_duplicate_identity_is_deduplicated_or_rejected() -> None:
    valid = copy.deepcopy(load_fixture("nasa_eonet_wildfires.json")["events"][0])
    assert isinstance(valid, dict)
    equivalent = copy.deepcopy(valid)
    conflicting = copy.deepcopy(valid)
    assert isinstance(conflicting, dict)
    conflicting["title"] = "Conflicting same EONET identity"
    for duplicate_events, expected_count, expected_issue in (
        ([valid, equivalent], 1, None),
        ([valid, conflicting], 0, "duplicate_identity"),
    ):
        client = client_for({"events": duplicate_events}, [])
        result = await NasaEonetWildfireAdapter(client=client).find_worldwide_events(
            WorldwideDisasterQuery(Disaster.WILDFIRE), now=NOW
        )
        assert len(result.records) == expected_count
        if expected_issue is not None:
            assert any(issue.reason_code == expected_issue for issue in result.issues)
        await client.aclose()


@pytest.mark.asyncio
async def test_eonet_rejects_bbox_hit_outside_country_polygon_and_supports_area() -> (
    None
):
    payload = load_fixture("nasa_eonet_wildfires.json")
    events = payload["events"]
    assert isinstance(events, list)
    valid = events[0]
    assert isinstance(valid, dict)
    geometry = valid["geometry"]
    assert isinstance(geometry, list)
    for observation in geometry:
        assert isinstance(observation, dict)
        observation["coordinates"] = [124.0, 40.0]
    requests: list[httpx.Request] = []
    client = client_for(payload, requests)
    adapter = NasaEonetWildfireAdapter(client=client, geography=StaticCountryCatalog())

    result = await adapter.find_recent_events(query(Disaster.WILDFIRE), now=NOW)

    assert result.records == ()
    assert any(issue.reason_code == "country_mismatch" for issue in result.issues)
    await client.aclose()

    area_payload = load_fixture("nasa_eonet_wildfires.json")
    area_events = area_payload["events"]
    assert isinstance(area_events, list)
    area_event = area_events[0]
    assert isinstance(area_event, dict)
    area_event["geometry"] = [
        {
            "date": "2026-08-17T10:00:00Z",
            "type": "Polygon",
            "coordinates": [
                [
                    [138.0, 34.0],
                    [141.0, 34.0],
                    [141.0, 37.0],
                    [138.0, 34.0],
                ]
            ],
            "magnitudeValue": 2500,
            "magnitudeUnit": "acres",
        }
    ]
    area_requests: list[httpx.Request] = []
    area_client = client_for(area_payload, area_requests)
    area_adapter = NasaEonetWildfireAdapter(
        client=area_client, geography=StaticCountryCatalog()
    )
    area_result = await area_adapter.find_recent_events(
        query(Disaster.WILDFIRE), now=NOW
    )
    assert len(area_result.records) == 1
    assert area_result.records[0].geometry is not None
    assert area_result.records[0].geometry.kind is EventGeometryKind.AREA
    await area_client.aclose()


@pytest.mark.asyncio
async def test_eonet_does_not_use_nested_urls_and_keeps_valid_siblings() -> None:
    payload = load_fixture("nasa_eonet_wildfires.json")
    requests: list[httpx.Request] = []
    client = client_for(payload, requests)
    adapter = NasaEonetWildfireAdapter(client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.WILDFIRE), now=NOW
    )

    assert [event.event_id for event in result.records] == ["eonet:EONET_FIXTURE_1"]
    assert any(issue.reason_code == "invalid_record" for issue in result.issues)
    assert result.records[0].source.canonical_url.startswith(
        "https://eonet.gsfc.nasa.gov/"
    )
    assert NasaEonetWildfireAdapter.allowed_hosts == frozenset({"eonet.gsfc.nasa.gov"})
    await client.aclose()


@pytest.mark.asyncio
async def test_eonet_accepts_its_json_body_with_provider_rss_media_type() -> None:
    requests: list[httpx.Request] = []
    client = client_for(
        load_fixture("nasa_eonet_wildfires.json"),
        requests,
        content_type="application/rss+xml; charset=utf-8",
    )
    adapter = NasaEonetWildfireAdapter(client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.WILDFIRE), now=NOW
    )

    assert result.records
    await client.aclose()


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
        "https://gis.earthdata.nasa.gov/gis01/"
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
    assert requests[0].url.path.startswith("/gis01/")
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
