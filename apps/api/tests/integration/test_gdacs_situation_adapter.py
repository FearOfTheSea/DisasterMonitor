"""GDACS observed impacts retain event identity and local observation scope."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.evidence.evidence_reconciliation import (
    build_evidence_packet,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    FactStatus,
    GeographicArea,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.gdacs_situation_adapter import (
    GdacsSituationAdapter,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)
FIXTURE = Path(__file__).parents[1] / "fixtures/gdacs_flood_details.json"
REPORT_FIXTURE = Path(__file__).parents[1] / "fixtures/gdacs_flood_report.html"


def scope():
    country = Country("PAK", "Pakistan", (), GeographicArea(23, 38, 60, 78))
    assert country is not None
    query = DisasterQuery(Disaster.FLOOD, country, "recent", ("damage",))
    source = SourceReference(
        "gdacs-floods",
        "GDACS",
        "Flood in Pakistan",
        "https://www.gdacs.org/report.aspx?eventtype=FL&eventid=1104136",
        None,
        None,
        NOW,
        SourceAuthority.SECONDARY,
    )
    event = DisasterEvent(
        "gdacs:fl:1104136",
        Disaster.FLOOD,
        "Pakistan",
        country,
        datetime(2026, 8, 31, 1, tzinfo=UTC),
        source,
    )
    return query, event


async def retrieve(payload, event=None):
    query, default_event = scope()
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await GdacsSituationAdapter(client=client).get_situation_reports(
            event or default_event, query, now=NOW
        )
    return batch, requests


@pytest.mark.asyncio
async def test_real_detail_payload_fills_report_without_inventing_totals():
    batch, requests = await retrieve(json.loads(FIXTURE.read_text()))
    assert requests[0].url.params["eventid"] == "1104136"
    query, event = scope()
    packet = build_evidence_packet(
        query, event, batch.records, warnings=(), retrieved_at=NOW
    )
    assert len(packet.facts) == 7
    assert all(fact.status is FactStatus.PRELIMINARY for fact in packet.facts)
    assert any(
        "Islamabad" in fact.label and fact.value.startswith("2")
        for fact in packet.facts
    )
    assert any(
        "Rawalpindi" in fact.label and fact.value.startswith("100")
        for fact in packet.facts
    )
    assert len({fact.claim_id for fact in packet.facts}) == 7
    assert all(
        fact.source.source_id == "gdacs-situation-reports" for fact in packet.facts
    )
    assert packet.facts[0].source.canonical_url.endswith(
        "detail=true&eventtype=FL&eventid=1104136&episodeid=2"
    )
    assert packet.completeness == "event_verified_with_event_specific_evidence"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("eventid", 999), ("eventtype", "EQ"), ("iso3", "NPL")]
)
async def test_mismatched_detail_is_rejected(field, value):
    payload = json.loads(FIXTURE.read_text())
    payload["properties"][field] = value
    batch, _ = await retrieve(payload)
    assert not batch.records
    assert batch.issues


@pytest.mark.asyncio
async def test_modelled_exposure_and_missing_impacts_are_not_reported_as_zero():
    payload = json.loads(FIXTURE.read_text())
    payload["properties"]["sendai"] = []
    payload["properties"]["impacts"] = [{"deaths": 10000}]
    batch, _ = await retrieve(payload)
    assert not batch.records
    assert batch.issues[0].reason_code == "empty_result"


@pytest.mark.asyncio
async def test_invalid_or_other_country_observations_do_not_enter_facts():
    payload = json.loads(FIXTURE.read_text())
    row = payload["properties"]["sendai"][0]
    rows = []
    for field, value in (
        ("sendaivalue", "-1"),
        ("sendaivalue", True),
        ("country", "Nepal"),
        ("dateinsert", "bad"),
        ("sendainame", "predicted deaths"),
    ):
        changed = deepcopy(row)
        changed[field] = value
        rows.append(changed)
    payload["properties"]["sendai"] = rows
    batch, _ = await retrieve(payload)
    assert not batch.records
    assert batch.issues


@pytest.mark.asyncio
async def test_unlinked_event_does_not_trigger_a_country_wide_impact_search():
    from dataclasses import replace

    _, event = scope()
    batch, requests = await retrieve({}, replace(event, event_id="other:123"))
    assert not requests
    assert not batch.records


@pytest.mark.asyncio
async def test_distinct_observation_intervals_on_the_same_day_remain_separate():
    payload = json.loads(FIXTURE.read_text())
    first = deepcopy(payload["properties"]["sendai"][0])
    second = deepcopy(first)
    second["onset_date"] = "2026-08-30T02:00:00"
    second["expires_date"] = "2026-09-02T02:00:00"
    second["sendaivalue"] = "3"
    payload["properties"]["sendai"] = [first, second]
    batch, _ = await retrieve(payload)
    query, event = scope()
    packet = build_evidence_packet(
        query, event, batch.records, warnings=(), retrieved_at=NOW
    )
    assert len(packet.facts) == 2
    assert len({fact.claim_id for fact in packet.facts}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("onset_date", "2026-09-26T01:00:00"),
        ("expires_date", "2026-08-01T01:00:00"),
        ("dateinsert", "2026-10-01T01:00:00"),
    ],
)
async def test_invalid_observation_periods_are_excluded(field, value):
    payload = json.loads(FIXTURE.read_text())
    row = deepcopy(payload["properties"]["sendai"][0])
    row[field] = value
    payload["properties"]["sendai"] = [row]
    batch, _ = await retrieve(payload)
    assert not batch.records


@pytest.mark.asyncio
async def test_detail_snapshot_provenance_reaches_every_fact():
    from types import SimpleNamespace

    snapshots = []

    async def record(payload):
        snapshots.append(payload)
        return SimpleNamespace(snapshot_id="snapshot:gdacs-impact-fixture")

    def handler(request):
        return httpx.Response(200, json=json.loads(FIXTURE.read_text()))

    query, event = scope()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await GdacsSituationAdapter(
            client=client, snapshot_recorder=record
        ).get_situation_reports(event, query, now=NOW)
    assert snapshots[0].rights_id == "gdacs-terms-of-use"
    assert batch.records[0].source.snapshot_id == "snapshot:gdacs-impact-fixture"
    assert all(
        fact.source.snapshot_id == "snapshot:gdacs-impact-fixture"
        for fact in batch.records[0].facts
    )


@pytest.mark.asyncio
async def test_source_outage_is_not_a_successful_empty_scan():
    from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError

    def handler(request):
        raise httpx.ConnectError("Offline fixture", request=request)

    query, event = scope()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DisasterProviderError):
            await GdacsSituationAdapter(client=client).get_situation_reports(
                event, query, now=NOW
            )


@pytest.mark.asyncio
async def test_transient_detail_outage_uses_dated_official_report_page_rows():
    from dataclasses import replace

    query, event = scope()
    event = replace(event, provider_ids=("gdacs:fl:1104136:2",))
    requests = []
    report_html = REPORT_FIXTURE.read_text()

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/geteventdata"):
            raise httpx.ReadTimeout("detail endpoint stalled", request=request)
        return httpx.Response(
            200,
            text=report_html,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await GdacsSituationAdapter(client=client).get_situation_reports(
            event, query, now=NOW
        )

    assert len(requests) == 3
    assert requests[-1].url.path == "/Floods/report.aspx"
    assert requests[-1].url.params["episodeid"] == "2"
    assert batch.records
    report = batch.records[0]
    assert len(report.facts) == 4
    assert {fact.value.split(" ", 1)[0] for fact in report.facts} == {
        "1",
        "2",
        "60",
        "100",
    }
    assert all("row-level period not specified" in fact.value for fact in report.facts)
    assert report.source.canonical_url.endswith(
        "detail=true&eventtype=FL&eventid=1104136&episodeid=2"
    )
    assert batch.issues[0].reason_code == "html_fallback"


@pytest.mark.asyncio
async def test_malformed_report_page_after_detail_outage_remains_unavailable():
    query, event = scope()

    def handler(request):
        if request.url.path.endswith("/geteventdata"):
            raise httpx.ReadTimeout("detail endpoint stalled", request=request)
        return httpx.Response(
            200,
            text="<html><h2>Impact Assessement as of 02-09-2026</h2></html>",
            headers={"content-type": "text/html"},
        )

    from disaster_monitor.infrastructure.disaster.errors import (
        DisasterProviderError,
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DisasterProviderError):
            await GdacsSituationAdapter(client=client).get_situation_reports(
                event, query, now=NOW
            )
