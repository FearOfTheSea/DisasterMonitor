"""Retained publisher text is inspectable without reclassifying or refetching it."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from disaster_monitor.application.incidents.discovery_projection import (
    discovery_incident,
)
from disaster_monitor.application.incidents.retained_reporting import (
    retained_reporting_page,
)
from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryEvent,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.presentation.http.api import create_schema_app

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Regional wildfires",
    "https://daily.example/report",
    NOW,
    None,
    NOW,
)
TEXT = (
    "Wildfires burned across the region. Five people died.\n## Local accounts\n"
    + "Original source context. " * 240
    + "A fire in Hilltown burned for 36 hours and killed one person.\n"
    + "A <script>source quote</script> is literal text. 😀"
)


def incident(text=TEXT):
    article = DiscoveryArticle(
        SOURCE, text, origin="wire:shared", bylines=("Author One",)
    )
    report = assess_article(article, ReportingInterval.at_start(7, NOW))
    report = replace(report, mention=report.mentions[0] if report.mentions else None)
    event = DiscoveryEvent(
        "local", Disaster.WILDFIRE, "Region", None, None, (report,), 1
    )
    return discovery_incident(
        event, NOW, scan_id="00000000-0000-4000-8000-000000000001"
    )


class Lookup:
    def __init__(self):
        self.value = incident()
        self.calls = []

    async def lookup(self, identifier):
        self.calls.append(identifier)
        if identifier != self.value.event_id:
            raise LookupError("Event not retained.")
        return self.value

    async def reporting_text(self, incident, capture_id, *, offset=0):
        return retained_reporting_page(incident, capture_id, offset=offset)


@pytest.fixture
async def client():
    lookup = Lookup()
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(active_incidents=lookup)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, lookup


async def capture(http, lookup):
    response = await http.get("/api/v1/incidents/" + lookup.value.event_id)
    assert response.status_code == 200
    body = response.json()
    report = body["discovery_reports"][0]
    assert report.get("capture_id"), (
        "Each retained capture needs an inspection identity."
    )
    return report["capture_id"], body


async def test_every_retained_character_and_attribution_can_be_read_without_new_claims(
    client,
):
    http, lookup = client
    capture_id, before = await capture(http, lookup)
    url = f"/api/v1/incidents/{lookup.value.event_id}/reporting/{capture_id}"
    offset = 0
    text = ""
    pages = 0
    while True:
        response = await http.get(url, params={"offset": offset})
        assert response.status_code == 200
        page = response.json()
        pages += 1
        assert page["capture_id"] == capture_id
        assert page["offset"] == offset
        assert page["source"] == before["discovery_reports"][0]["source"]
        assert page["bylines"] == ["Author One"] and page["origin"] == "wire:shared"
        assert len(page["text"]) <= 4000
        assert page["total_characters"] == len(TEXT)
        assert page["unavailable_reason"] is None
        text += page["text"]
        if page["next_offset"] is None:
            break
        assert page["next_offset"] == len(text)
        offset = page["next_offset"]
    assert pages > 1 and text == TEXT
    after = (await http.get("/api/v1/incidents/" + lookup.value.event_id)).json()
    assert after == before
    assert all(
        "Hilltown" not in r.get("mention_excerpt", "")
        for r in after["discovery_reports"]
    )
    assert "A fire in Hilltown" in text


async def test_capture_version_changes_with_text_even_at_the_same_url_and_clocks(
    client,
):
    http, lookup = client
    old, _ = await capture(http, lookup)
    lookup.value = incident(TEXT + " A publisher correction.")
    new, _ = await capture(http, lookup)
    assert old != new
    response = await http.get(
        f"/api/v1/incidents/{lookup.value.event_id}/reporting/{old}"
    )
    assert response.status_code == 404


@pytest.mark.parametrize("offset", [-1, 999999999999, "bad"])
async def test_invalid_offsets_cannot_produce_false_empty_completion(client, offset):
    http, lookup = client
    capture_id, _ = await capture(http, lookup)
    response = await http.get(
        f"/api/v1/incidents/{lookup.value.event_id}/reporting/{capture_id}",
        params={"offset": offset},
    )
    assert response.status_code == 422


async def test_unknown_event_or_capture_returns_explicit_not_found(client):
    http, lookup = client
    for path in (
        f"{lookup.value.event_id}/reporting/unknown",
        "other-event/reporting/unknown",
    ):
        assert (await http.get("/api/v1/incidents/" + path)).status_code == 404


async def test_unreadable_capture_retains_an_explicit_unavailable_state(client):
    http, lookup = client
    lookup.value = incident("")
    capture_id, _ = await capture(http, lookup)
    page = (
        await http.get(
            f"/api/v1/incidents/{lookup.value.event_id}/reporting/{capture_id}"
        )
    ).json()
    assert page["text"] == "" and page["next_offset"] is None
    assert page["unavailable_reason"]
