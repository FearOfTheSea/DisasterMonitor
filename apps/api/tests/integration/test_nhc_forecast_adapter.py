from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    CycloneMapSemanticRole,
    Disaster,
    DisasterEvent,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.nhc_forecast_adapter import (
    NhcCycloneForecastAdapter,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 31, 6, tzinfo=UTC)
JAPAN = StaticCountryCatalog().get_by_alpha3("JPN")
assert JAPAN is not None


def _event(
    *,
    name: str = "KARINA",
    latitude: float = 17.1,
    longitude: float = -123.8,
    source_id: str = "gdacs-tropical-cyclones",
) -> DisasterEvent:
    source = SourceReference(
        source_id=source_id,
        publisher="Global Disaster Alert and Coordination System (GDACS)",
        title=f"Tropical Cyclone {name}-26",
        canonical_url="https://www.gdacs.org/report.aspx?eventtype=TC&eventid=42",
        published_at=None,
        updated_at=NOW,
        retrieved_at=NOW,
        authority=SourceAuthority.SECONDARY,
    )
    return DisasterEvent(
        event_id="gdacs:tc:42",
        disaster=Disaster.TROPICAL_CYCLONE,
        location="Pacific Ocean",
        country=JAPAN,
        event_time=datetime(2026, 8, 25, tzinfo=UTC),
        source=source,
        geometry=point_event_geometry(latitude, longitude, source),
    )


def _query() -> DisasterQuery:
    return DisasterQuery(
        Disaster.TROPICAL_CYCLONE,
        JAPAN,
        "recent",
        ("latest",),
    )


def _empty_feed(basin: str = "Atlantic") -> bytes:
    return f"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>NHC GIS Data ({basin})</title>
      <item><title>There are no tropical cyclones at this time.</title></item>
    </channel></rss>""".encode()


def _forecast_feed(
    *,
    storm_id: str = "EP112026",
    name: str = "Karina",
    center: str = "17.1, -123.8",
    track_url: str | None = (
        "https://www.nhc.noaa.gov/storm_graphics/api/EP112026_015adv_TRACK.kmz"
    ),
    cone_url: str | None = (
        "https://www.nhc.noaa.gov/storm_graphics/api/EP112026_015adv_CONE.kmz"
    ),
    extra_items: str = "",
) -> bytes:
    products = ""
    if track_url:
        products += f"""<item>
          <title>Advisory #015 Forecast Track [kmz] - Hurricane {name}
          (EP1/{storm_id})</title>
          <pubDate>Mon, 31 Aug 2026 02:56:24 GMT</pubDate><link>{track_url}</link>
        </item>"""
    if cone_url:
        products += f"""<item>
          <title>Advisory #015 Cone of Uncertainty [kmz] - Hurricane {name}
          (EP1/{storm_id})</title>
          <pubDate>Mon, 31 Aug 2026 02:56:19 GMT</pubDate><link>{cone_url}</link>
        </item>"""
    return f"""<?xml version="1.0"?>
    <rss version="2.0" xmlns:nhc="https://www.nhc.noaa.gov"><channel>
      <pubDate>Mon, 31 Aug 2026 03:00:00 GMT</pubDate>
      <title>National Hurricane Center GIS Data</title>
      <item><title>Summary - Hurricane {name} (EP1/{storm_id})</title>
        <pubDate>Mon, 31 Aug 2026 02:53:45 GMT</pubDate>
        <nhc:Cyclone><nhc:center>{center}</nhc:center><nhc:name>{name}</nhc:name>
        <nhc:atcf>{storm_id}</nhc:atcf></nhc:Cyclone>
      </item>{products}{extra_items}
    </channel></rss>""".encode()


def _track_kmz(
    *, invalid_time: bool = False, invalid_coordinate: bool = False
) -> bytes:
    valid_time = "not-a-time" if invalid_time else "2:00 AM HST August 31, 2026"
    longitude = "999" if invalid_coordinate else "-124.9"
    kml = f"""<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2">
      <Document><name>EP112026 (Advisory #15) - Forecast Track</name><Folder>
        <Placemark><description><![CDATA[<tr><td>Advisory Information</td></tr>
          <tr><td>Valid at: 5:00 PM HST August 30, 2026</td></tr>]]></description>
          <Point><coordinates>-123.8,17.1,0</coordinates></Point></Placemark>
        <Placemark><description><![CDATA[<tr><td>12 hr Forecast</td></tr>
          <tr><td>Valid at: {valid_time}</td></tr>]]></description>
          <Point><coordinates>{longitude},17.1,0</coordinates></Point></Placemark>
        <Placemark><description><![CDATA[<tr><td>24 hr Forecast</td></tr>
          <tr><td>Valid at: 2:00 PM HST August 31, 2026</td></tr>]]></description>
          <Point><coordinates>-126.6,17.4,0</coordinates></Point></Placemark>
        <Placemark><description><![CDATA[<tr><td>36 hr Forecast</td></tr>
          <tr><td>Valid at: 2:00 AM HST September 01, 2026</td></tr>]]></description>
          <Point><coordinates>-128.4,17.9,0</coordinates></Point></Placemark>
      </Folder></Document></kml>"""
    return _kmz("forecast_track.kml", kml)


def _cone_kmz(*, malformed: bool = False) -> bytes:
    coordinates = (
        "broken"
        if malformed
        else "-124.0,16.0,0 -130.0,16.0,0 -130.0,20.0,0 -124.0,16.0,0"
    )
    kml = f"""<?xml version="1.0"?><kml xmlns="http://earth.google.com/kml/2.1">
      <Document><Placemark><Polygon><outerBoundaryIs><LinearRing>
        <coordinates>{coordinates}</coordinates>
      </LinearRing></outerBoundaryIs></Polygon><ExtendedData>
        <Data name="advisoryDate"><value>500 PM HST Sun Aug 30 2026</value></Data>
        <Data name="fcstpd"><value>120</value></Data>
        <Data name="atcfid"><value>EP112026</value></Data>
      </ExtendedData></Placemark></Document></kml>"""
    return _kmz("forecast_cone.kml", kml)


def _kmz(name: str, content: str) -> bytes:
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return payload.getvalue()


def _client(
    requests: list[httpx.Request],
    *,
    ep_feed: bytes | None = None,
    track: bytes | None = None,
    cone: bytes | None = None,
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/gis-ep.xml":
            content = ep_feed if ep_feed is not None else _forecast_feed()
            content_type = "application/rss+xml"
        elif path in {"/gis-at.xml", "/gis-cp.xml"}:
            content = _empty_feed()
            content_type = "application/rss+xml"
        elif path.endswith("TRACK.kmz"):
            content = track if track is not None else _track_kmz()
            content_type = "application/vnd.google-earth.kmz"
        elif path.endswith("CONE.kmz"):
            content = cone if cone is not None else _cone_kmz()
            content_type = "application/vnd.google-earth.kmz"
        else:
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            content=content,
            headers={"content-type": content_type},
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_parses_official_forecast_track_and_uncertainty_with_provenance() -> None:
    requests: list[httpx.Request] = []
    snapshots: list[object] = []

    async def record_snapshot(payload: object) -> object:
        snapshots.append(payload)
        return SimpleNamespace(snapshot_id=f"snapshot:{len(snapshots)}")

    client = _client(requests)
    adapter = NhcCycloneForecastAdapter(
        client=client,
        snapshot_recorder=record_snapshot,
    )

    result = await adapter.get_situation_reports(_event(), _query(), now=NOW)

    assert result.issues == ()
    assert len(result.records) == 1
    report = result.records[0]
    assert report.correlation is CorrelationStatus.MATCHED
    assert report.source.source_id == "noaa-nhc-cyclone-forecast"
    assert report.source.authority is SourceAuthority.NATIONAL_AUTHORITY
    assert report.provider_event_ids == ("atcf:EP112026",)
    assert "unique storm name and source-backed center proximity" in report.narrative
    assert [item.semantic_role for item in report.supplemental_geometry] == [
        CycloneMapSemanticRole.FORECAST_TRACK,
        CycloneMapSemanticRole.UNCERTAINTY_AREA,
    ]
    track, cone = report.supplemental_geometry
    assert [(point.latitude, point.longitude) for point in track.coordinates] == [
        (17.1, -124.9),
        (17.4, -126.6),
        (17.9, -128.4),
    ]
    assert [point.valid_at for point in track.coordinates] == [
        datetime(2026, 8, 31, 12, tzinfo=UTC),
        datetime(2026, 9, 1, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 12, tzinfo=UTC),
    ]
    assert track.issued_at == datetime(2026, 8, 31, 2, 56, 24, tzinfo=UTC)
    assert [(point.latitude, point.longitude) for point in cone.coordinates] == [
        (16.0, -124.0),
        (16.0, -130.0),
        (20.0, -130.0),
        (16.0, -124.0),
    ]
    assert cone.valid_from == datetime(2026, 8, 31, 3, tzinfo=UTC)
    assert cone.valid_to == datetime(2026, 9, 5, 3, tzinfo=UTC)
    assert all(
        "not an observed storm footprint" in item.limitation for item in (track, cone)
    )
    assert len(requests) == 5
    assert {request.url.host for request in requests} == {"www.nhc.noaa.gov"}
    assert len(snapshots) == 5
    assert {item.rights_id for item in snapshots} == {"noaa-nws-public-domain"}
    await client.aclose()


@pytest.mark.asyncio
async def test_unique_identity_is_required_and_ambiguous_matches_fail_closed() -> None:
    no_match_requests: list[httpx.Request] = []
    no_match_client = _client(no_match_requests)
    no_match = await NhcCycloneForecastAdapter(
        client=no_match_client
    ).get_situation_reports(_event(name="OTHER"), _query(), now=NOW)

    assert no_match.records == ()
    assert no_match.issues[-1].reason_code == "forecast_not_applicable"
    assert len(no_match_requests) == 3
    await no_match_client.aclose()

    ambiguous_requests: list[httpx.Request] = []
    duplicate = _forecast_feed(storm_id="EP992026")

    def handler(request: httpx.Request) -> httpx.Response:
        ambiguous_requests.append(request)
        content = _forecast_feed() if request.url.path == "/gis-ep.xml" else duplicate
        return httpx.Response(
            200,
            content=content,
            headers={"content-type": "application/rss+xml"},
            request=request,
        )

    ambiguous_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ambiguous = await NhcCycloneForecastAdapter(
        client=ambiguous_client
    ).get_situation_reports(_event(), _query(), now=NOW)

    assert ambiguous.records == ()
    assert ambiguous.issues[-1].reason_code == "identity_not_reconciled"
    assert len(ambiguous_requests) == 3
    await ambiguous_client.aclose()


@pytest.mark.asyncio
async def test_partial_products_render_only_the_valid_source_product() -> None:
    requests: list[httpx.Request] = []
    client = _client(
        requests,
        ep_feed=_forecast_feed(cone_url=None),
        track=_track_kmz(invalid_time=True),
    )

    result = await NhcCycloneForecastAdapter(client=client).get_situation_reports(
        _event(), _query(), now=NOW
    )

    assert len(result.records) == 1
    assert [item.semantic_role for item in result.records[0].supplemental_geometry] == [
        CycloneMapSemanticRole.FORECAST_TRACK
    ]
    assert len(result.records[0].supplemental_geometry[0].coordinates) == 2
    assert any(item.reason_code == "invalid_product_record" for item in result.issues)
    assert all(
        item.semantic_role is not CycloneMapSemanticRole.UNCERTAINTY_AREA
        and item.semantic_role is not CycloneMapSemanticRole.WIND_RADII
        for item in result.records[0].supplemental_geometry
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_malformed_geometry_and_unallowlisted_product_host_are_excluded() -> None:
    malformed_requests: list[httpx.Request] = []
    malformed_client = _client(
        malformed_requests,
        track=_track_kmz(invalid_coordinate=True),
        cone=_cone_kmz(malformed=True),
    )
    malformed = await NhcCycloneForecastAdapter(
        client=malformed_client
    ).get_situation_reports(_event(), _query(), now=NOW)

    assert len(malformed.records) == 1
    assert [
        layer.semantic_role for layer in malformed.records[0].supplemental_geometry
    ] == [CycloneMapSemanticRole.FORECAST_TRACK]
    assert len(malformed.records[0].supplemental_geometry[0].coordinates) == 2
    assert any(
        item.reason_code == "invalid_product_record" for item in malformed.issues
    )
    assert any(item.reason_code == "invalid_product" for item in malformed.issues)
    await malformed_client.aclose()

    host_requests: list[httpx.Request] = []
    host_client = _client(
        host_requests,
        ep_feed=_forecast_feed(
            track_url="https://unapproved.example/track.kmz",
            cone_url=None,
        ),
    )
    host_result = await NhcCycloneForecastAdapter(
        client=host_client
    ).get_situation_reports(_event(), _query(), now=NOW)

    assert host_result.records == ()
    assert any(
        item.reason_code == "source_policy_violation" for item in host_result.issues
    )
    assert len(host_requests) == 3
    await host_client.aclose()


@pytest.mark.asyncio
async def test_unsupported_products_and_response_size_bound_fail_safely() -> None:
    unsupported_requests: list[httpx.Request] = []
    unsupported_client = _client(
        unsupported_requests,
        ep_feed=_forecast_feed(
            track_url=None,
            cone_url=None,
            extra_items="<item><title>Advisory Wind Field [shp]</title><link>https://www.nhc.noaa.gov/wind.zip</link></item>",
        ),
    )
    unsupported = await NhcCycloneForecastAdapter(
        client=unsupported_client
    ).get_situation_reports(_event(), _query(), now=NOW)

    assert unsupported.records == ()
    assert unsupported.issues[-1].reason_code == "forecast_products_unavailable"
    assert len(unsupported_requests) == 3
    await unsupported_client.aclose()

    bounded_requests: list[httpx.Request] = []
    bounded_client = _client(bounded_requests)
    with pytest.raises(DisasterProviderResponseError) as raised:
        await NhcCycloneForecastAdapter(
            client=bounded_client,
            max_response_bytes=100,
        ).get_situation_reports(_event(), _query(), now=NOW)

    assert raised.value.failure.reason_code == "response_too_large"
    assert len(bounded_requests) == 1
    await bounded_client.aclose()


@pytest.mark.asyncio
async def test_ineligible_or_geometryless_events_do_not_query_forecasts() -> None:
    requests: list[httpx.Request] = []
    client = _client(requests)
    adapter = NhcCycloneForecastAdapter(client=client)
    other_source = await adapter.get_situation_reports(
        _event(source_id="other-source"), _query(), now=NOW
    )
    geometryless_event = _event()
    geometryless = DisasterEvent(
        event_id=geometryless_event.event_id,
        disaster=geometryless_event.disaster,
        location=geometryless_event.location,
        country=geometryless_event.country,
        event_time=geometryless_event.event_time,
        source=geometryless_event.source,
    )
    no_geometry = await adapter.get_situation_reports(geometryless, _query(), now=NOW)
    wrong_query = await adapter.get_situation_reports(
        _event(),
        DisasterQuery(Disaster.FLOOD, JAPAN, "recent", ("latest",)),
        now=NOW,
    )

    assert other_source.records == () and other_source.issues == ()
    assert no_geometry.records == ()
    assert no_geometry.issues[0].reason_code == "event_geometry_unavailable"
    assert wrong_query.records == () and wrong_query.issues == ()
    assert requests == []
    await client.aclose()
