import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery, WorldwideDisasterQuery
from disaster_monitor.domain.disaster import (
    Disaster,
    EventGeographyStatus,
    SourceAuthority,
)
from disaster_monitor.infrastructure.disaster.smithsonian_gvp_adapter import (
    SmithsonianGvpAdapter,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

NOW = datetime(2026, 8, 18, 12, tzinfo=UTC)
FIXTURES = Path(__file__).parents[1] / "fixtures"


def load_json(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def query(country_code: str = "JPN") -> DisasterQuery:
    country = StaticCountryCatalog().get_by_alpha3(country_code)
    assert country is not None
    return DisasterQuery(
        Disaster.VOLCANIC_ERUPTION,
        country,
        "specified",
        ("latest developments",),
        date_from=datetime(2026, 7, 16, tzinfo=UTC),
        date_to=datetime(2026, 7, 22, 23, 59, tzinfo=UTC),
    )


def client_for(
    requests: list[httpx.Request],
    *,
    wvar: str | None = None,
    volcanoes: object | None = None,
    eruptions: object | None = None,
) -> httpx.AsyncClient:
    wvar_body = wvar or (FIXTURES / "smithsonian_wvar_weekly.html").read_text(
        encoding="utf-8"
    )
    volcano_payload = volcanoes or load_json("smithsonian_gvp_volcanoes.json")
    eruption_payload = eruptions or load_json("smithsonian_gvp_eruptions.json")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "volcano.si.edu":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=wvar_body.encode(),
                request=request,
            )
        if "Holocene_Volcanoes" in request.url.params.get("typeNames", ""):
            payload = volcano_payload
        else:
            payload = eruption_payload
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode(),
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_valid_continuing_activity_is_source_backed_and_enriched() -> None:
    requests: list[httpx.Request] = []
    snapshots: list[object] = []

    async def record(payload: object) -> object:
        snapshots.append(payload)
        return SimpleNamespace(snapshot_id=f"snapshot:{len(snapshots)}")

    client = client_for(requests)
    adapter = SmithsonianGvpAdapter(
        geography=StaticCountryCatalog(), client=client, snapshot_recorder=record
    )
    result = await adapter.find_recent_events(query(), now=NOW)

    event = next(
        item for item in result.records if item.event_id == "gvp-eruption:41234"
    )
    assert event.event_time == datetime(2004, 10, 23, tzinfo=UTC)
    assert event.provider_ids == (
        "gvp-volcano:282030",
        "gvp-eruption:41234",
        "wvar:GVP.WVAR20260716-282030",
    )
    assert event.country.alpha3_code == "JPN"
    assert event.geography_status is EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
    assert event.geometry is not None
    assert event.geometry.coordinates[0].latitude == 29.638
    assert event.geometry.coordinates[0].longitude == 129.714
    assert event.source.authority is SourceAuthority.SCIENTIFIC_AUTHORITY
    assert event.source.canonical_url == (
        "https://volcano.si.edu/reports_weekly.cfm/showreport.cfm?"
        "gvpvar=GVP.WVAR20260716-282030"
    )
    assert event.source.snapshot_id == "snapshot:1"
    assert len(snapshots) == 3
    assert all(
        request.url.host in {"volcano.si.edu", "webservices.volcano.si.edu"}
        for request in requests
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_new_activity_uses_gvp_start_and_worldwide_is_countryless() -> None:
    requests: list[httpx.Request] = []
    client = client_for(requests)
    adapter = SmithsonianGvpAdapter(geography=StaticCountryCatalog(), client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.VOLCANIC_ERUPTION, time_window_days=6),
        now=datetime(2026, 7, 22, 23, 59, tzinfo=UTC),
    )

    event = next(
        item for item in result.records if item.event_id == "gvp-eruption:41235"
    )
    assert event.event_time == datetime(2026, 7, 18, tzinfo=UTC)
    assert event.location.startswith("Ahyi")
    assert not hasattr(event, "country")
    assert len(requests) == 3
    wfs_requests = [
        item for item in requests if item.url.host == "webservices.volcano.si.edu"
    ]
    assert len(wfs_requests) == 2
    assert all(
        request.url.params.get("outputFormat") == "application/json"
        for request in wfs_requests
    )
    volcano_request = next(
        item
        for item in wfs_requests
        if "Holocene_Volcanoes" in item.url.params.get("typeNames", "")
    )
    assert volcano_request.url.params.get("count") == "100"
    assert set(volcano_request.url.params.get("propertyName", "").split(",")) == {
        "Volcano_Number",
        "Volcano_Name",
        "Country",
        "Region",
        "Latitude",
        "Longitude",
    }
    assert "999999" in volcano_request.url.params.get("CQL_FILTER", "")
    await client.aclose()


@pytest.mark.asyncio
async def test_unrest_other_unknown_and_malformed_rows_are_not_eruptions() -> None:
    requests: list[httpx.Request] = []
    client = client_for(requests)
    adapter = SmithsonianGvpAdapter(geography=StaticCountryCatalog(), client=client)

    result = await adapter.find_worldwide_events(
        WorldwideDisasterQuery(Disaster.VOLCANIC_ERUPTION), now=NOW
    )

    assert {item.event_id for item in result.records} == {
        "gvp-eruption:41234",
        "gvp-eruption:41235",
    }
    reasons = {issue.reason_code for issue in result.issues}
    assert "non_eruptive_report_type" in reasons
    assert "unsupported_report_type" in reasons
    assert "invalid_record" in reasons
    assert not any(
        "national-observatory.example" in str(request.url) for request in requests
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_uncertain_wvar_and_gvp_dates_are_excluded_without_fabrication() -> None:
    wvar = (
        (FIXTURES / "smithsonian_wvar_weekly.html")
        .read_text(encoding="utf-8")
        .replace("2004 Oct 23", "2004 Oct 23 ± 4 days")
    )
    eruptions = load_json("smithsonian_gvp_eruptions.json")
    features = eruptions["features"]
    assert isinstance(features, list)
    first = features[0]
    assert isinstance(first, dict)
    properties = first["properties"]
    assert isinstance(properties, dict)
    properties["StartDateDayUncertainty"] = 4
    requests: list[httpx.Request] = []
    client = client_for(requests, wvar=wvar, eruptions=eruptions)
    adapter = SmithsonianGvpAdapter(geography=StaticCountryCatalog(), client=client)

    result = await adapter.find_recent_events(query(), now=NOW)

    assert not any(item.event_id == "gvp-eruption:41234" for item in result.records)
    assert any(
        issue.reason_code == "event_time_precision_unavailable"
        for issue in result.issues
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_point_outside_polygon_requires_explicit_gvp_country_affiliation() -> (
    None
):
    volcanoes = load_json("smithsonian_gvp_volcanoes.json")
    features = volcanoes["features"]
    assert isinstance(features, list)
    ahyi = features[1]
    assert isinstance(ahyi, dict)
    properties = ahyi["properties"]
    assert isinstance(properties, dict)
    properties["Country"] = "Vanuatu"
    requests: list[httpx.Request] = []
    client = client_for(requests, volcanoes=volcanoes)
    adapter = SmithsonianGvpAdapter(geography=StaticCountryCatalog(), client=client)

    result = await adapter.find_recent_events(query(), now=NOW)

    assert all(item.event_id != "gvp-eruption:41235" for item in result.records)
    assert any(issue.reason_code == "country_mismatch" for issue in result.issues)
    await client.aclose()


@pytest.mark.asyncio
async def test_point_inside_maintained_country_polygon_is_accepted() -> None:
    volcanoes = load_json("smithsonian_gvp_volcanoes.json")
    features = volcanoes["features"]
    assert isinstance(features, list)
    suwanosejima = features[0]
    assert isinstance(suwanosejima, dict)
    properties = suwanosejima["properties"]
    assert isinstance(properties, dict)
    properties["Latitude"] = 35.0
    properties["Longitude"] = 135.0
    requests: list[httpx.Request] = []
    client = client_for(requests, volcanoes=volcanoes)
    adapter = SmithsonianGvpAdapter(geography=StaticCountryCatalog(), client=client)

    result = await adapter.find_recent_events(query(), now=NOW)

    event = next(
        item for item in result.records if item.event_id == "gvp-eruption:41234"
    )
    assert event.geography_status is EventGeographyStatus.IN_COUNTRY
    assert event.geometry is not None
    assert event.geometry.coordinates[0].latitude == 35.0
    assert event.geometry.coordinates[0].longitude == 135.0
    await client.aclose()


def _wvar_without_row_report() -> str:
    report_link = (
        '          <a href="showreport.cfm?gvpvar=GVP.WVAR20260716-282030">Report</a>\n'
    )
    return (
        (FIXTURES / "smithsonian_wvar_weekly.html")
        .read_text(encoding="utf-8")
        .replace(report_link, "")
    )


async def _suwanosejima_event(wvar: str):
    requests: list[httpx.Request] = []
    client = client_for(requests, wvar=wvar)
    result = await SmithsonianGvpAdapter(
        geography=StaticCountryCatalog(), client=client
    ).find_worldwide_events(WorldwideDisasterQuery(Disaster.VOLCANIC_ERUPTION), now=NOW)
    await client.aclose()
    return next(
        item for item in result.records if item.event_id == "gvp-eruption:41234"
    )


@pytest.mark.asyncio
async def test_wvar_provenance_is_row_local_against_page_decoys() -> None:
    decoy_282030 = '<a href="showreport.cfm?gvpvar=GVP.WVAR20260801-282030">Decoy</a>'
    decoy_999999 = (
        '<a href="showreport.cfm?gvpvar=GVP.WVAR20260801-999999">Other volcano</a>'
    )
    without_row = _wvar_without_row_report()
    variants = (
        without_row.replace("<body>", f"<body>{decoy_282030}", 1),
        without_row.replace("</body>", f"{decoy_282030}</body>", 1),
        without_row.replace("<body>", f"<body>{decoy_999999}", 1),
    )
    for html in variants:
        event = await _suwanosejima_event(html)
        assert event.source.canonical_url == (
            "https://volcano.si.edu/reports_weekly.cfm?weekstart=20260716"
        )
        assert event.provider_ids == (
            "gvp-volcano:282030",
            "gvp-eruption:41234",
        )


@pytest.mark.asyncio
async def test_wvar_row_local_report_wins_over_conflicting_page_decoy() -> None:
    html = (
        (FIXTURES / "smithsonian_wvar_weekly.html")
        .read_text(encoding="utf-8")
        .replace(
            "<body>",
            '<body><a href="showreport.cfm?gvpvar=GVP.WVAR20260801-282030">Decoy</a>',
            1,
        )
    )

    event = await _suwanosejima_event(html)

    assert event.source.canonical_url == (
        "https://volcano.si.edu/reports_weekly.cfm/showreport.cfm?"
        "gvpvar=GVP.WVAR20260716-282030"
    )
    assert event.provider_ids[-1] == "wvar:GVP.WVAR20260716-282030"


@pytest.mark.asyncio
async def test_smithsonian_duplicate_source_identity_is_not_silently_merged() -> None:
    html = (
        (FIXTURES / "smithsonian_wvar_weekly.html")
        .read_text(encoding="utf-8")
        .replace(
            "    </table>",
            """      <tr>
        <td>
          <a href="volcano.cfm?vn=282030">Suwanosejima</a>
          <a href="showreport.cfm?gvpvar=GVP.WVAR20260801-282030">Conflicting report</a>
        </td>
        <td>Japan</td>
        <td>Ryukyu Volcanic Arc</td>
        <td>2004 Oct 23</td>
        <td>Continuing Eruptive Activity</td>
      </tr>
    </table>""",
            1,
        )
    )
    requests: list[httpx.Request] = []
    client = client_for(requests, wvar=html)
    result = await SmithsonianGvpAdapter(
        geography=StaticCountryCatalog(), client=client
    ).find_worldwide_events(WorldwideDisasterQuery(Disaster.VOLCANIC_ERUPTION), now=NOW)

    assert all(item.event_id != "gvp-eruption:41234" for item in result.records)
    assert any(issue.reason_code == "duplicate_identity" for issue in result.issues)
    await client.aclose()


@pytest.mark.asyncio
async def test_smithsonian_gvp_feature_order_does_not_change_normalized_events() -> (
    None
):
    volcanoes = load_json("smithsonian_gvp_volcanoes.json")
    eruptions = load_json("smithsonian_gvp_eruptions.json")
    assert isinstance(volcanoes["features"], list)
    assert isinstance(eruptions["features"], list)
    reversed_volcanoes = {
        **volcanoes,
        "features": list(reversed(volcanoes["features"])),
    }
    reversed_eruptions = {
        **eruptions,
        "features": list(reversed(eruptions["features"])),
    }

    forward_client = client_for([], volcanoes=volcanoes, eruptions=eruptions)
    reverse_client = client_for(
        [], volcanoes=reversed_volcanoes, eruptions=reversed_eruptions
    )
    forward = await SmithsonianGvpAdapter(
        geography=StaticCountryCatalog(), client=forward_client
    ).find_worldwide_events(WorldwideDisasterQuery(Disaster.VOLCANIC_ERUPTION), now=NOW)
    reverse = await SmithsonianGvpAdapter(
        geography=StaticCountryCatalog(), client=reverse_client
    ).find_worldwide_events(WorldwideDisasterQuery(Disaster.VOLCANIC_ERUPTION), now=NOW)

    assert {
        (item.event_id, item.event_time, item.source.canonical_url, item.provider_ids)
        for item in forward.records
    } == {
        (item.event_id, item.event_time, item.source.canonical_url, item.provider_ids)
        for item in reverse.records
    }
    await forward_client.aclose()
    await reverse_client.aclose()
