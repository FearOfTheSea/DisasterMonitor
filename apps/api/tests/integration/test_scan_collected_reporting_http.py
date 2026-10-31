"""Unclassified retained evidence stays inspectable independently of hazard events."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from disaster_monitor.application.incidents.collected_reporting import (
    collected_reporting_text,
)
from disaster_monitor.application.incidents.retained_reporting import (
    reporting_capture_id,
)
from disaster_monitor.domain.discovery import (
    AssessedReport,
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.presentation.http.api import create_schema_app

NOW = datetime(2026, 10, 27, 6, tzinfo=UTC)
TEXT = (
    "A worker died when material fell onto road machinery. "
    + "Context 😀 <script>quote</script>. " * 180
)


def report(index, *, text=TEXT, eligibility="unknown_publication"):
    article = DiscoveryArticle(
        SourceReference(
            "news",
            "Local Daily",
            f"Retained account {index}",
            f"https://daily.example/{index}",
            None,
            None,
            NOW + timedelta(seconds=index),
        ),
        text,
        origin="wire:shared",
        bylines=("A. Reporter",),
        original_url="https://wire.example/original",
    )
    return AssessedReport(article, None, eligibility, ())


class RetainedScans:
    def __init__(self):
        self.run = DiscoveryRun(
            str(uuid4()),
            ReportingInterval.at_start(7, NOW),
            status="incomplete",
            reports=tuple(report(i) for i in range(53)),
        )
        self.calls = []

    async def get(self, identifier):
        self.calls.append(identifier)
        if identifier != self.run.scan_id:
            raise LookupError("Scan not retained.")
        return self.run

    async def reporting_text(self, identifier, capture_id, *, offset=0):
        return collected_reporting_text(
            await self.get(identifier), capture_id, offset=offset
        )


@pytest.fixture
async def client():
    scans = RetainedScans()
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(discovery_scans=scans)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, scans


async def test_all_unclassified_captures_are_paged_with_attribution_and_no_events(
    client,
):
    http, scans = client
    url = f"/api/v1/discovery-scans/{scans.run.scan_id}/reporting"
    pages = []
    offset, version = 0, None
    while True:
        params = {"offset": offset}
        if version:
            params["version"] = version
        response = await http.get(url, params=params)
        assert response.status_code == 200
        page = response.json()
        pages.append(page)
        assert page["total"] == 53 and page["offset"] == offset
        assert len(page["items"]) <= 25
        version = page["version"]
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    items = [item for page in pages for item in page["items"]]
    assert len(pages) == 3 and len({item["capture_id"] for item in items}) == 53
    for item in items:
        assert item["disaster"] is None
        assert item["eligibility"] == "unknown_publication"
        assert item["source"]["published_at"] is None
        assert item["bylines"] == ["A. Reporter"]
        assert item["origin"] == "wire:shared" and not item["event_linked"]
    assert scans.run.events == () and len(scans.run.reports) == 53


async def test_exact_unclassified_body_and_continuation_are_scan_scoped(client):
    http, scans = client
    article = scans.run.reports[0].article
    capture = reporting_capture_id(article)
    url = f"/api/v1/discovery-scans/{scans.run.scan_id}/reporting/{capture}"
    offset, text = 0, ""
    while True:
        response = await http.get(url, params={"offset": offset})
        assert response.status_code == 200
        page = response.json()
        assert page["capture_id"] == capture
        assert page["bylines"] == ["A. Reporter"]
        assert page["origin"] == "wire:shared"
        assert page["original_url"] == "https://wire.example/original"
        assert len(page["text"]) <= 4000
        text += page["text"]
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert text == TEXT
    assert (await http.get(url + "?offset=-1")).status_code == 422
    assert (await http.get(url.replace(capture, "unknown"))).status_code == 404
    assert (
        await http.get(url.replace(scans.run.scan_id, str(uuid4())))
    ).status_code == 404


async def test_paging_rejects_stale_catalog_instead_of_silently_skipping_reports(
    client,
):
    http, scans = client
    url = f"/api/v1/discovery-scans/{scans.run.scan_id}/reporting"
    first = await http.get(url)
    assert first.status_code == 200
    page = first.json()
    scans.run = replace(scans.run, reports=(*scans.run.reports, report(100)))
    stale = await http.get(url, params={"offset": 25, "version": page["version"]})
    assert stale.status_code == 409
    assert (await http.get(url, params={"offset": 25})).status_code == 422


async def test_same_url_changed_body_remains_another_capture(client):
    http, scans = client
    original = scans.run.reports[0]
    revised = replace(
        original, article=replace(original.article, text="A corrected account.")
    )
    scans.run = replace(scans.run, reports=(original, revised))
    response = await http.get(f"/api/v1/discovery-scans/{scans.run.scan_id}/reporting")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2 and items[0]["capture_id"] != items[1]["capture_id"]


async def test_linked_filter_and_outside_publication_status_are_preserved(client):
    from disaster_monitor.domain.disaster_types import Disaster
    from disaster_monitor.domain.discovery import DiscoveryEvent

    http, scans = client
    linked = replace(report(0), disaster=Disaster.FLOOD, eligibility="eligible")
    outside = replace(report(1), eligibility="outside_interval")
    unknown = report(2)
    event = DiscoveryEvent(
        "linked", Disaster.FLOOD, "Unknown", None, None, (linked,), 1
    )
    scans.run = replace(scans.run, reports=(linked, outside, unknown), events=(event,))
    url = f"/api/v1/discovery-scans/{scans.run.scan_id}/reporting"
    unlinked = await http.get(url)
    assert unlinked.status_code == 200 and unlinked.json()["total"] == 2
    assert not any(item["event_linked"] for item in unlinked.json()["items"])
    all_reports = await http.get(url, params={"unlinked_only": False})
    assert all_reports.status_code == 200 and all_reports.json()["total"] == 3
    outside_item = next(
        item
        for item in all_reports.json()["items"]
        if item["capture_id"] == reporting_capture_id(outside.article)
    )
    assert outside_item["eligibility"] == "outside_interval"
    assert sum(item["event_linked"] for item in all_reports.json()["items"]) == 1
    assert scans.run.events == (event,)


async def test_empty_catalog_and_out_of_range_offset_are_explicit(client):
    http, scans = client
    scans.run = replace(scans.run, reports=())
    url = f"/api/v1/discovery-scans/{scans.run.scan_id}/reporting"
    response = await http.get(url)
    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0
    assert response.json()["next_offset"] is None
    assert (await http.get(url, params={"offset": 100})).status_code == 422
