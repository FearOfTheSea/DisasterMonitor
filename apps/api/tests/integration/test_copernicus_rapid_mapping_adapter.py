import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.evidence.source_evidence_policy import (
    validate_situation_evidence,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    Country,
    Disaster,
    DisasterEvent,
    FactStatus,
    GeographicArea,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.disaster.copernicus_ems_mapping_adapter import (
    CopernicusRapidMappingAdapter,
)
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError

NOW = datetime(2024, 9, 4, 12, tzinfo=UTC)
ITALY = Country(
    "ITA",
    "Italy",
    ("Italian Republic",),
    GeographicArea(35.0, 48.0, 6.0, 19.0),
)
FIXTURES = Path(__file__).parents[1] / "fixtures"
ACTIVATIONS = (FIXTURES / "copernicus_rapid_mapping_mass_activations.json").read_bytes()
DETAIL = (
    FIXTURES / "copernicus_rapid_mapping_mass_activation_detail.json"
).read_bytes()


def disaster_event(
    disaster: Disaster = Disaster.LANDSLIDE,
    *,
    geometry: bool = True,
    provider_ids: tuple[str, ...] = ("coolr:fixture",),
) -> DisasterEvent:
    source = SourceReference(
        source_id=f"selected-{disaster.value}",
        publisher="Selected event provider",
        title="Selected event",
        canonical_url="https://example.test/event",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
    )
    return DisasterEvent(
        event_id=f"{disaster.value}:selected",
        disaster=disaster,
        location="San Felice a Cancello, Campania",
        country=ITALY,
        event_time=datetime(2024, 8, 27, 13, tzinfo=UTC),
        source=source,
        geometry=point_event_geometry(40.81, 14.61, source) if geometry else None,
        provider_ids=provider_ids,
    )


def disaster_query(disaster: Disaster = Disaster.LANDSLIDE) -> DisasterQuery:
    return DisasterQuery(
        disaster,
        ITALY,
        "August 27, 2024",
        ("2024-08-27",),
        date_from=datetime(2024, 8, 27, tzinfo=UTC),
        date_to=datetime(2024, 8, 28, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_rapid_mapping_requires_a_correlated_delivered_crisis_product() -> None:
    requests: list[httpx.Request] = []
    snapshots: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = DETAIL if "public-activations/" in request.url.path else ACTIVATIONS
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=payload,
            request=request,
        )

    async def record_snapshot(payload: object) -> object:
        snapshots.append(payload)
        return SimpleNamespace(snapshot_id=f"snapshot:cems:{len(snapshots)}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CopernicusRapidMappingAdapter(
        client=client,
        snapshot_recorder=record_snapshot,
    )

    result = await adapter.get_situation_reports(
        disaster_event(), disaster_query(), now=NOW
    )

    assert result.issues == ()
    assert len(result.records) == 1
    report = result.records[0]
    assert report.event_id == "landslide:selected"
    assert report.disaster is Disaster.LANDSLIDE
    assert report.correlation is CorrelationStatus.POSSIBLE
    assert report.source.source_id == "copernicus-rapid-mapping-landslides"
    assert report.source.authority is SourceAuthority.SECONDARY
    assert report.source.snapshot_id == "snapshot:cems:2"
    assert report.source.canonical_url.endswith("/activations/EMSR751")
    assert "feasible grading product" in report.narrative
    assert "does not independently prove event identity" in report.narrative
    assert [(fact.label, fact.value, fact.status) for fact in report.facts] == [
        ("Rapid Mapping activation", "EMSR751", FactStatus.CONFIRMED),
        ("Delivered crisis-mapping product types", "GRA", FactStatus.CONFIRMED),
    ]
    assert report.measurements == ()
    assert report.provider_event_ids == ("cems:EMSR751",)
    assert len(requests) == 2
    assert requests[0].url.params["category"] == "mass"
    assert requests[0].url.params["limit"] == "100"
    assert requests[1].url.params["code"] == "EMSR751"
    assert len(snapshots) == 2
    assert snapshots[0].rights_id == "copernicus-data-legal-notice"
    assert (
        validate_situation_evidence(
            report,
            disaster_query(),
            source_id=adapter.source_id,
            allowed_hosts=adapter.allowed_hosts,
        )
        is report
    )
    await client.aclose()


RAPID_MAPPING_CASES = (
    (
        Disaster.EARTHQUAKE,
        "earthquake",
        "Earthquake",
        "copernicus-rapid-mapping-earthquakes",
    ),
    (Disaster.FLOOD, "flood", "Flood", "copernicus-rapid-mapping-floods"),
    (
        Disaster.WILDFIRE,
        "wildfire",
        "Wildfire",
        "copernicus-rapid-mapping-wildfires",
    ),
    (
        Disaster.LANDSLIDE,
        "mass",
        "Mass movement",
        "copernicus-rapid-mapping-landslides",
    ),
    (
        Disaster.TROPICAL_CYCLONE,
        "storm",
        "Storm",
        "copernicus-rapid-mapping-tropical-cyclones",
    ),
    (
        Disaster.VOLCANIC_ERUPTION,
        "volcanic",
        "Volcanic activity",
        "copernicus-rapid-mapping-volcanic-eruptions",
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("disaster", "query_category", "response_category", "source_id"),
    RAPID_MAPPING_CASES,
)
async def test_rapid_mapping_supports_each_configured_disaster_category(
    disaster: Disaster,
    query_category: str,
    response_category: str,
    source_id: str,
) -> None:
    requests: list[httpx.Request] = []
    activations = json.loads(ACTIVATIONS)
    activation = activations["results"][0]
    activation["category"] = response_category
    activation["name"] = f"{response_category} in Campania Region, Italy"
    event_provider_ids = ("coolr:fixture",)
    if disaster is Disaster.TROPICAL_CYCLONE:
        activation["gdacsId"] = "TC1001230"
        event_provider_ids = ("gdacs:tc:1001230",)
    activations["results"] = [activation]
    detail = json.loads(DETAIL)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = detail if "public-activations/" in request.url.path else activations
        return httpx.Response(200, json=payload, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CopernicusRapidMappingAdapter(disaster=disaster, client=client)

    result = await adapter.get_situation_reports(
        disaster_event(disaster, provider_ids=event_provider_ids),
        disaster_query(disaster),
        now=NOW,
    )

    assert result.issues == ()
    assert len(result.records) == 1
    assert result.records[0].disaster is disaster
    assert result.records[0].source.source_id == source_id
    assert requests[0].url.params["category"] == query_category
    await client.aclose()


@pytest.mark.asyncio
async def test_non_cyclonic_storm_without_shared_gdacs_identity_is_excluded() -> None:
    activations = json.loads(ACTIVATIONS)
    activation = activations["results"][0]
    activation["category"] = "Storm"
    activation["name"] = "Storm in Campania Region, Italy"
    activation["gdacsId"] = None
    activations["results"] = [activation]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=activations, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CopernicusRapidMappingAdapter(
        disaster=Disaster.TROPICAL_CYCLONE,
        client=client,
    )

    result = await adapter.get_situation_reports(
        disaster_event(
            Disaster.TROPICAL_CYCLONE,
            provider_ids=("gdacs:tc:1001230",),
        ),
        disaster_query(Disaster.TROPICAL_CYCLONE),
        now=NOW,
    )

    assert result.records == ()
    assert result.issues[0].reason_code == "empty_result"
    await client.aclose()


@pytest.mark.asyncio
async def test_rapid_mapping_retains_shared_gdacs_identity() -> None:
    activations = json.loads(ACTIVATIONS)
    activation = activations["results"][0]
    activation["category"] = "Flood"
    activation["gdacsId"] = "FL1104081"
    activation["eventTime"] = "2024-08-01T12:00:00"
    activation["centroid"] = "POINT (9.190 45.464)"
    activations["results"] = [activation]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = (
            json.loads(DETAIL)
            if "public-activations/" in request.url.path
            else activations
        )
        return httpx.Response(200, json=payload, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CopernicusRapidMappingAdapter(disaster=Disaster.FLOOD, client=client)

    result = await adapter.get_situation_reports(
        disaster_event(
            Disaster.FLOOD,
            provider_ids=("cems-gfm:fixture", "gdacs:fl:1104081"),
        ),
        disaster_query(Disaster.FLOOD),
        now=NOW,
    )

    assert result.records[0].correlation is CorrelationStatus.MATCHED
    assert result.records[0].provider_event_ids == (
        "cems:EMSR751",
        "gdacs:fl:1104081",
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_activation_without_feasible_delineation_or_grading_is_not_evidence() -> (
    None
):
    detail = json.loads(DETAIL)
    detail["results"][0]["aois"][0]["products"] = [
        {
            "type": "REF",
            "feasible": True,
            "mapsCount": 1,
            "version": {"status": "DELIVERED"},
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = (
            detail
            if "public-activations/" in request.url.path
            else json.loads(ACTIVATIONS)
        )
        return httpx.Response(200, json=payload, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await CopernicusRapidMappingAdapter(client=client).get_situation_reports(
        disaster_event(), disaster_query(), now=NOW
    )

    assert result.records == ()
    assert result.issues[0].reason_code == "no_qualifying_mapping_product"
    await client.aclose()


@pytest.mark.asyncio
async def test_rapid_mapping_never_runs_for_other_hazards_or_unbounded_geometry() -> (
    None
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = CopernicusRapidMappingAdapter(client=client)
    event = disaster_event()

    wrong = await adapter.get_situation_reports(
        event,
        DisasterQuery(Disaster.FLOOD, ITALY, "recent", ("latest",)),
        now=NOW,
    )
    geometryless = await adapter.get_situation_reports(
        disaster_event(geometry=False), disaster_query(), now=NOW
    )

    assert wrong.records == ()
    assert geometryless.records == ()
    assert geometryless.issues[0].reason_code == "event_geometry_unavailable"
    assert requests == []
    await client.aclose()


@pytest.mark.asyncio
async def test_rapid_mapping_preserves_retryable_provider_failure() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(DisasterProviderError) as raised:
        await CopernicusRapidMappingAdapter(client=client).get_situation_reports(
            disaster_event(), disaster_query(), now=NOW
        )

    assert raised.value.failure.reason_code == "http_server_error"
    assert raised.value.failure.retryable is True
    assert len(requests) == 2
    await client.aclose()
