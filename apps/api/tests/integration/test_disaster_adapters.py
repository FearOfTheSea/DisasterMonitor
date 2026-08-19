import json
from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.disaster import (
    DisasterQuery,
    WorldwideDisasterQuery,
)
from disaster_monitor.domain.disaster import (
    BoundaryValidationQuality,
    Country,
    Disaster,
    EventGeographyStatus,
    GeographicArea,
    MeasurementKind,
)
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderError,
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.usgs_adapter import UsgsEarthquakeAdapter
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
VENEZUELA = CATALOG.get_by_alpha3("VEN")
VIETNAM = CATALOG.get_by_alpha3("VNM")
assert JAPAN is not None and VENEZUELA is not None and VIETNAM is not None
INDONESIA = Country(
    alpha3_code="IDN",
    canonical_name="Indonesia",
    aliases=(),
    geographic_area=GeographicArea(
        min_latitude=-10.909668,
        max_latitude=5.907031,
        min_longitude=95.206641,
        max_longitude=140.975977,
        validation_quality=BoundaryValidationQuality.POLYGON,
        polygons=(
            (
                (-8.0, 121.4),
                (-8.0, 121.8),
                (-8.6, 121.8),
                (-8.6, 121.4),
            ),
        ),
    ),
)
QUERY = DisasterQuery(
    disaster=Disaster.EARTHQUAKE,
    country=JAPAN,
    time_intent="recent",
    focus=("damage", "latest developments"),
)


def client_for(
    payload: object, *, status: int = 200, content_type: str = "application/json"
):
    def handler(request: httpx.Request) -> httpx.Response:
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


def usgs_payload() -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "us7000fixture",
                "properties": {
                    "time": int(
                        datetime(2026, 8, 5, 10, 0, tzinfo=UTC).timestamp() * 1000
                    ),
                    "updated": int(
                        datetime(2026, 8, 5, 10, 5, tzinfo=UTC).timestamp() * 1000
                    ),
                    "mag": 5.8,
                    "magType": "mww",
                    "place": "near Honshu, Japan",
                    "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000fixture",
                    "mmi": 5.1,
                    "sig": 512,
                },
                "geometry": {"type": "Point", "coordinates": [140.0, 36.0, 20.0]},
            }
        ],
    }


@pytest.mark.asyncio
async def test_usgs_adapter_translates_valid_geojson_and_missing_optional_fields() -> (
    None
):
    payload = usgs_payload()
    payload["features"][0]["properties"].pop("mmi")  # type: ignore[index]
    client = client_for(payload)
    adapter = UsgsEarthquakeAdapter(geography=CATALOG, client=client)

    result = await adapter.find_recent_events(QUERY, now=NOW)

    assert len(result.records) == 1
    assert result.records[0].event_id == "usgs:us7000fixture"
    assert (
        next(
            item.value
            for item in result.records[0].measurements
            if item.kind is MeasurementKind.MAGNITUDE
        )
        == 5.8
    )
    assert not any(
        item.kind is MeasurementKind.INTENSITY
        for item in result.records[0].measurements
    )
    await client.aclose()


@pytest.mark.parametrize(
    ("payload", "content_type", "max_bytes", "status"),
    [
        ({"not": "geojson"}, "application/json", 1_000_000, 200),
        (b"not-json", "text/plain", 1_000_000, 200),
        (b"{}", "application/json", 1, 200),
    ],
)
async def test_usgs_adapter_rejects_malformed_unexpected_or_oversized_payloads(
    payload, content_type, max_bytes, status
) -> None:
    client = client_for(payload, content_type=content_type, status=status)
    adapter = UsgsEarthquakeAdapter(
        geography=CATALOG, client=client, max_response_bytes=max_bytes
    )

    with pytest.raises((DisasterProviderError, DisasterProviderResponseError)):
        await adapter.find_recent_events(QUERY, now=NOW)
    await client.aclose()


async def test_usgs_keeps_valid_feature_when_sibling_is_malformed() -> None:
    payload = usgs_payload()
    payload["features"].append({})  # type: ignore[union-attr]
    client = client_for(payload)

    result = await UsgsEarthquakeAdapter(
        geography=CATALOG, client=client
    ).find_recent_events(QUERY, now=NOW)

    assert [event.event_id for event in result.records] == ["usgs:us7000fixture"]
    assert result.issues[0].reason_code == "invalid_record"
    await client.aclose()


@pytest.mark.asyncio
async def test_usgs_adapter_surfaces_http_failure() -> None:
    client = client_for({"error": "offline"}, status=503)
    adapter = UsgsEarthquakeAdapter(geography=CATALOG, client=client)

    with pytest.raises(DisasterProviderError):
        await adapter.find_recent_events(QUERY, now=NOW)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_usgs_generic_query_is_bounded_and_magnitude_ordered() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(usgs_payload()).encode(),
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = UsgsEarthquakeAdapter(geography=CATALOG, client=client)
    await adapter.find_recent_events(QUERY, now=NOW)
    query_params = dict(requests[0].url.params.multi_items())
    assert query_params["orderby"] == "magnitude"
    assert query_params["limit"] == "50"
    assert query_params["minmagnitude"] == "4.5"
    assert query_params["minlatitude"] == "20.0"
    assert query_params["maxlatitude"] == "46.0"
    assert query_params["minlongitude"] == "122.0"
    assert query_params["maxlongitude"] == "154.0"
    assert "includeallorigins" not in query_params
    assert "includeallmagnitudes" not in query_params
    await client.aclose()


@pytest.mark.asyncio
async def test_usgs_worldwide_query_has_no_country_bounds_and_preserves_event() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(usgs_payload()).encode(),
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = UsgsEarthquakeAdapter(geography=CATALOG, client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.EARTHQUAKE), now=NOW
    )
    params = dict(requests[0].url.params.multi_items())

    assert params["orderby"] == "time"
    assert params["minmagnitude"] == "4.5"
    assert "minlatitude" not in params
    assert "maxlatitude" not in params
    assert "minlongitude" not in params
    assert "maxlongitude" not in params
    assert result.records[0].event_id == "usgs:us7000fixture"
    assert result.records[0].location == "near Honshu, Japan"
    await client.aclose()


@pytest.mark.asyncio
async def test_usgs_uses_non_japan_bounds_and_canonical_country() -> None:
    requests: list[httpx.Request] = []
    payload = usgs_payload()
    feature = payload["features"][0]  # type: ignore[index]
    feature["properties"]["place"] = "Sucre, Venezuela"  # type: ignore[index]
    feature["geometry"]["coordinates"] = [-63.5, 10.4, 12.0]  # type: ignore[index]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode(),
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    query = DisasterQuery(
        Disaster.EARTHQUAKE,
        VENEZUELA,
        "recent",
        ("latest developments",),
    )
    result = await UsgsEarthquakeAdapter(
        geography=CATALOG, client=client
    ).find_recent_events(query, now=NOW)
    params = dict(requests[0].url.params.multi_items())

    assert params["minlatitude"] == "0.63"
    assert params["maxlatitude"] == "12.2"
    assert params["minlongitude"] == "-73.35"
    assert params["maxlongitude"] == "-59.8"
    assert result.records[0].country == VENEZUELA
    assert result.records[0].event_id == "usgs:us7000fixture"
    assert result.records[0].source.published_at == datetime(
        2026, 8, 5, 10, 0, tzinfo=UTC
    )
    assert result.records[0].source.updated_at == datetime(
        2026, 8, 5, 10, 5, tzinfo=UTC
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_usgs_excludes_coordinate_inside_rectangle_but_outside_country() -> None:
    payload = usgs_payload()
    feature = payload["features"][0]  # type: ignore[index]
    feature["geometry"]["coordinates"] = [123.0, 21.0, 20.0]  # type: ignore[index]
    client = client_for(payload)

    result = await UsgsEarthquakeAdapter(
        geography=CATALOG, client=client
    ).find_recent_events(QUERY, now=NOW)

    assert result.records == ()
    assert result.issues[0].reason_code == "country_mismatch"
    await client.aclose()


@pytest.mark.asyncio
async def test_usgs_accepts_near_shore_event_with_explicit_country_place() -> None:
    payload = usgs_payload()
    feature = payload["features"][0]  # type: ignore[index]
    feature["properties"]["place"] = "68 km NNW of Ende, Indonesia"  # type: ignore[index]
    feature["geometry"]["coordinates"] = [121.3517, -8.3101, 10.0]  # type: ignore[index]
    client = client_for(payload)
    query = DisasterQuery(
        Disaster.EARTHQUAKE,
        INDONESIA,
        "recent",
        ("damage",),
    )

    result = await UsgsEarthquakeAdapter(
        geography=CATALOG, client=client
    ).find_recent_events(query, now=NOW)

    assert len(result.records) == 1
    assert (
        result.records[0].geography_status
        == EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
    )
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_code", "expected_attempts"),
    [
        (429, "rate_limited", 2),
        (503, "http_server_error", 2),
        (403, "configuration_rejected", 1),
    ],
)
async def test_http_failures_keep_typed_issue_and_bounded_retry(
    status: int, expected_code: str, expected_attempts: int
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1 and status in {429, 503}:
            return httpx.Response(
                status,
                headers={"content-type": "application/json"},
                content=b"{}",
                request=request,
            )
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            content=b"{}",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    composite = CompositeDisasterEventProvider(
        (UsgsEarthquakeAdapter(geography=CATALOG, client=client),)
    )
    result = await composite.find_recent_events(QUERY, now=NOW)
    assert attempts == expected_attempts
    assert result.records == ()
    assert result.issues[0].reason_code == expected_code
    assert result.issues[0].retryable is (status in {429, 503})
    assert result.issues[0].http_status == status
    await client.aclose()
