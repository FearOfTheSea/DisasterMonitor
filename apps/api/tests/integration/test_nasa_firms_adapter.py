from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    Disaster,
    DisasterEvent,
    FactStatus,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.disaster.nasa_firms_adapter import (
    NasaFirmsObservationAdapter,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
assert JAPAN is not None
FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "nasa_firms_viirs_observations.csv"
).read_bytes()


def wildfire_event() -> DisasterEvent:
    source = SourceReference(
        source_id="selected-wildfire",
        publisher="Selected wildfire provider",
        title="Selected wildfire",
        canonical_url="https://example.test/wildfire",
        published_at=NOW,
        updated_at=NOW,
        retrieved_at=NOW,
    )
    return DisasterEvent(
        event_id="wildfire:selected",
        disaster=Disaster.WILDFIRE,
        location="Central Japan",
        country=JAPAN,
        event_time=datetime(2026, 8, 20, tzinfo=UTC),
        source=source,
        geometry=point_event_geometry(35.0, 139.0, source),
        provider_ids=("wildfire:selected",),
    )


def wildfire_query() -> DisasterQuery:
    return DisasterQuery(Disaster.WILDFIRE, JAPAN, "recent", ("latest",))


@pytest.mark.asyncio
async def test_unconfigured_firms_makes_no_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = NasaFirmsObservationAdapter(client=client)

    result = await adapter.get_situation_reports(
        wildfire_event(), wildfire_query(), now=NOW
    )

    assert adapter.configured is False
    assert result.records == ()
    assert requests == []
    await client.aclose()


@pytest.mark.asyncio
async def test_firms_aggregates_nearby_hotspots_as_possible_observation_evidence() -> (
    None
):
    requests: list[httpx.Request] = []
    snapshots: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/csv"},
            content=FIXTURE,
            request=request,
        )

    async def record_snapshot(payload: object) -> object:
        snapshots.append(payload)
        return SimpleNamespace(snapshot_id="snapshot:firms-fixture")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = NasaFirmsObservationAdapter(
        map_key="secret-map-key",
        client=client,
        snapshot_recorder=record_snapshot,
    )

    result = await adapter.get_situation_reports(
        wildfire_event(), wildfire_query(), now=NOW
    )

    assert result.issues == ()
    assert len(result.records) == 1
    report = result.records[0]
    assert report.event_id == "wildfire:selected"
    assert report.disaster is Disaster.WILDFIRE
    assert report.correlation is CorrelationStatus.POSSIBLE
    assert report.source.source_id == "nasa-firms-observations"
    assert report.source.authority is SourceAuthority.SCIENTIFIC_AUTHORITY
    assert report.source.snapshot_id == "snapshot:firms-fixture"
    assert report.source.canonical_url == "https://firms.modaps.eosdis.nasa.gov/map/"
    assert "secret-map-key" not in report.source.canonical_url
    assert "2 VIIRS fire/thermal anomaly detections" in report.narrative
    assert "do not confirm" in report.narrative
    assert [(fact.label, fact.value, fact.status) for fact in report.facts] == [
        ("Nearby thermal anomaly detections", "2", FactStatus.PRELIMINARY),
        (
            "Observation interval (UTC)",
            "2026-08-23T03:15:00+00:00 to 2026-08-23T04:45:00+00:00",
            FactStatus.PRELIMINARY,
        ),
    ]
    assert report.measurements == ()
    assert len(requests) == 1
    assert "/secret-map-key/VIIRS_SNPP_NRT/" in requests[0].url.path
    assert len(snapshots) == 1
    assert snapshots[0].rights_id == "nasa-earth-science-data-use"
    assert "secret-map-key" not in str(snapshots[0].canonical_request_identity)
    await client.aclose()


@pytest.mark.asyncio
async def test_firms_never_runs_for_non_wildfire_or_geometryless_event() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=FIXTURE, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = NasaFirmsObservationAdapter(map_key="secret-map-key", client=client)
    event = wildfire_event()

    wrong = await adapter.get_situation_reports(
        event,
        DisasterQuery(Disaster.FLOOD, JAPAN, "recent", ("latest",)),
        now=NOW,
    )
    geometryless = await adapter.get_situation_reports(
        DisasterEvent(
            event.event_id,
            event.disaster,
            event.location,
            event.country,
            event.event_time,
            event.source,
        ),
        wildfire_query(),
        now=NOW,
    )

    assert wrong.records == ()
    assert geometryless.records == ()
    assert geometryless.issues[0].reason_code == "event_geometry_unavailable"
    assert requests == []
    await client.aclose()
