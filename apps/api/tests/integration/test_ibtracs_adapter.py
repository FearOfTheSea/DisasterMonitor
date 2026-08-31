from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    CycloneMapGeometryKind,
    CycloneMapSemanticRole,
    Disaster,
    DisasterEvent,
    FactStatus,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError
from disaster_monitor.infrastructure.disaster.ibtracs_adapter import IbtracsTrackAdapter
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
CATALOG = StaticCountryCatalog()
JAPAN = CATALOG.get_by_alpha3("JPN")
assert JAPAN is not None
FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "ibtracs_active_tracks.csv"
).read_bytes()


def cyclone_event(*, source_id: str = "gdacs-tropical-cyclones") -> DisasterEvent:
    source = SourceReference(
        source_id=source_id,
        publisher="Global Disaster Alert and Coordination System (GDACS); source: JTWC",
        title="Tropical Cyclone SAUDEL-26",
        canonical_url="https://www.gdacs.org/report.aspx?eventtype=TC&eventid=1001305",
        published_at=None,
        updated_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
        retrieved_at=NOW,
        authority=SourceAuthority.SECONDARY,
    )
    return DisasterEvent(
        event_id="gdacs:tc:1001305",
        disaster=Disaster.TROPICAL_CYCLONE,
        location="Northern Mariana Islands, Japan, China",
        country=JAPAN,
        event_time=datetime(2026, 8, 18, 12, tzinfo=UTC),
        source=source,
        geometry=point_event_geometry(22.6, 139.4, source),
        provider_ids=("gdacs:tc:1001305", "gdacs:tc:1001305:24"),
    )


def cyclone_query() -> DisasterQuery:
    return DisasterQuery(
        Disaster.TROPICAL_CYCLONE,
        JAPAN,
        "recent",
        ("latest",),
    )


@pytest.mark.asyncio
async def test_ibtracs_reconciles_identity_from_name_start_and_track_proximity() -> (
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
        return SimpleNamespace(snapshot_id="snapshot:ibtracs-active")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = IbtracsTrackAdapter(
        client=client,
        snapshot_recorder=record_snapshot,
    )

    result = await adapter.get_situation_reports(
        cyclone_event(), cyclone_query(), now=NOW
    )

    assert result.issues == ()
    assert len(result.records) == 1
    report = result.records[0]
    assert report.event_id == "gdacs:tc:1001305"
    assert report.disaster is Disaster.TROPICAL_CYCLONE
    assert report.correlation is CorrelationStatus.MATCHED
    assert report.source.source_id == "noaa-ibtracs-tracks"
    assert report.source.authority is SourceAuthority.SCIENTIFIC_AUTHORITY
    assert report.source.snapshot_id == "snapshot:ibtracs-active"
    assert report.source.canonical_url.endswith("ibtracs.ACTIVE.list.v04r01.csv")
    assert "contributing track agencies: jtwc_wp" in report.source.publisher
    assert "storm name, track start, and track proximity" in report.narrative
    assert "not an independent live-event authority" in report.narrative
    assert [(fact.label, fact.value, fact.status) for fact in report.facts] == [
        ("IBTrACS storm identifier", "2026231N08155", FactStatus.PRELIMINARY),
        (
            "Retained track interval (UTC)",
            "2026-08-18T12:00:00+00:00 to 2026-08-23T00:00:00+00:00",
            FactStatus.PRELIMINARY,
        ),
        ("Retained track points", "3", FactStatus.PRELIMINARY),
    ]
    assert report.measurements == ()
    assert report.provider_event_ids == (
        "ibtracs:2026231N08155",
        "atcf:WP172026",
    )
    assert len(report.supplemental_geometry) == 1
    track = report.supplemental_geometry[0]
    assert track.semantic_role is CycloneMapSemanticRole.PROVISIONAL_TRACK
    assert track.geometry_kind is CycloneMapGeometryKind.TRACK
    assert track.provisional is True
    assert track.storm_id == "2026231N08155"
    assert [
        (item.latitude, item.longitude, item.valid_at) for item in track.coordinates
    ] == [
        (7.9, 154.9, datetime(2026, 8, 18, 12, tzinfo=UTC)),
        (20.4, 143.6, datetime(2026, 8, 22, 18, tzinfo=UTC)),
        (21.0, 142.3, datetime(2026, 8, 23, 0, tzinfo=UTC)),
    ]
    assert track.valid_from == datetime(2026, 8, 18, 12, tzinfo=UTC)
    assert track.valid_to == datetime(2026, 8, 23, 0, tzinfo=UTC)
    assert "not a forecast" in track.limitation
    assert all(
        item.semantic_role is not CycloneMapSemanticRole.FORECAST_TRACK
        for item in report.supplemental_geometry
    )
    assert len(requests) == 1
    assert len(snapshots) == 1
    assert snapshots[0].rights_id == "noaa-ncei-data"
    await client.aclose()


@pytest.mark.asyncio
async def test_ibtracs_does_not_attach_without_gdacs_selection_or_identity_match() -> (
    None
):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/csv"},
            content=FIXTURE,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = IbtracsTrackAdapter(client=client)

    other_source = await adapter.get_situation_reports(
        cyclone_event(source_id="other-cyclone-source"), cyclone_query(), now=NOW
    )
    event = cyclone_event()
    unmatched_source = SourceReference(
        source_id=event.source.source_id,
        publisher=event.source.publisher,
        title="Tropical Cyclone DIFFERENT-26",
        canonical_url=event.source.canonical_url,
        published_at=event.source.published_at,
        updated_at=event.source.updated_at,
        retrieved_at=event.source.retrieved_at,
        authority=event.source.authority,
    )
    unmatched = await adapter.get_situation_reports(
        DisasterEvent(
            event_id=event.event_id,
            disaster=event.disaster,
            location=event.location,
            country=event.country,
            event_time=event.event_time,
            source=unmatched_source,
            geometry=point_event_geometry(22.6, 139.4, unmatched_source),
            provider_ids=event.provider_ids,
        ),
        cyclone_query(),
        now=NOW,
    )

    assert other_source.records == ()
    assert unmatched.records == ()
    assert unmatched.issues[0].reason_code == "identity_not_reconciled"
    assert len(requests) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_ibtracs_never_runs_for_other_hazards_or_geometryless_cyclones() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = IbtracsTrackAdapter(client=client)
    event = cyclone_event()
    geometryless = DisasterEvent(
        event.event_id,
        event.disaster,
        event.location,
        event.country,
        event.event_time,
        event.source,
    )

    wrong = await adapter.get_situation_reports(
        event,
        DisasterQuery(Disaster.FLOOD, JAPAN, "recent", ("latest",)),
        now=NOW,
    )
    unbounded = await adapter.get_situation_reports(
        geometryless, cyclone_query(), now=NOW
    )

    assert wrong.records == ()
    assert unbounded.records == ()
    assert unbounded.issues[0].reason_code == "event_geometry_unavailable"
    assert requests == []
    await client.aclose()


@pytest.mark.asyncio
async def test_ibtracs_preserves_retryable_provider_failure() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(DisasterProviderError) as raised:
        await IbtracsTrackAdapter(client=client).get_situation_reports(
            cyclone_event(), cyclone_query(), now=NOW
        )

    assert raised.value.failure.reason_code == "http_server_error"
    assert raised.value.failure.retryable is True
    assert len(requests) == 2
    await client.aclose()
