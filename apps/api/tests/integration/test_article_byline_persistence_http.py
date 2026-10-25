"""Bylines survive collection storage and HTTP without joining unrelated reports."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import (
    DiscoveryBatch,
    DiscoveryRun,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)
from disaster_monitor.presentation.http.api import create_schema_app

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def article(publisher, path):
    return parse_discovery_article(
        '<meta name="articleAuthor" content="News Agency">'
        '<meta property="article:published_time" content="2026-10-25T00:00:00Z">'
        "<article><p>Floodwaters killed two people.</p></article>",
        url=f"https://publisher.example/{path}",
        title="Flood report",
        publisher=publisher,
        retrieved_at=NOW,
        indexed_at=None,
    )


async def test_declared_byline_survives_real_sqlite_collection_restart(tmp_path):
    path = tmp_path / "collection.sqlite"
    store = SQLiteCollectionJournal(path)
    scan = DiscoveryRun("byline-roundtrip", ReportingInterval.at_start(1, NOW))
    partition = CollectionPartition("news", "flood", scan.interval.start, NOW)
    await store.attach(scan, (partition,), now=NOW, budget=10)
    work = await store.claim("search", "worker", now=NOW)
    original = article("Daily", "report")
    assert await store.commit_page(work, CollectionPage(articles=(original,)), now=NOW)
    restarted = SQLiteCollectionJournal(path)
    (retained,) = (await restarted.snapshot(scan.scan_id, now=NOW)).articles
    assert retained == original
    assert retained.bylines == ("News Agency",)
    assert retained.origin is None


async def test_legacy_stored_report_without_bylines_stays_readable_without_guessing(
    tmp_path,
):
    store = FileDiscoveryStore(tmp_path)
    identifier = str(uuid4())
    interval = ReportingInterval.at_start(1, NOW)
    run = DiscoveryRun(
        identifier,
        interval,
        reports=(assess_article(article("Daily", "one"), interval),),
    )
    await store.save(run)
    path = tmp_path / f"{identifier}.json"
    payload = json.loads(path.read_bytes())
    del payload["reports"][0]["article"]["bylines"]
    path.write_text(json.dumps(payload))
    retained = await FileDiscoveryStore(tmp_path).read(identifier)
    assert retained.reports[0].article.bylines == ()
    assert retained.reports[0].article.source.publisher == "Daily"
    assert retained.reports[0].article.origin is None


@pytest.mark.parametrize("days", [1, 3, 7, 14, 30])
async def test_same_byline_does_not_join_unlocated_distinct_report_candidates(
    tmp_path, days
):
    articles = (article("Local Daily", "one"), article("Metro Daily", "two"))

    class Feed:
        source_id = "controlled"

        async def discover(self, *, interval):
            yield DiscoveryBatch(articles=articles, successful_operations=1)

    service = DiscoveryScanService(
        (Feed(),), FileDiscoveryStore(tmp_path), clock=lambda: NOW
    )
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(discovery_scans=service)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/discovery-scans", json={"reporting_days": days}
            )
            identifier = response.json()["scan_id"]
            await service.wait(identifier)
            result = (await client.get(f"/api/v1/discovery-scans/{identifier}")).json()
        incidents = result["snapshot"]["incidents"]
        assert len(incidents) == 2
        assert {e["source"]["publisher"] for e in incidents} == {
            "Local Daily",
            "Metro Daily",
        }
        for incident in incidents:
            assert incident["identity_status"] == "candidate"
            assert incident["independent_origins"] == 0
            (report,) = incident["discovery_reports"]
            assert report["bylines"] == ["News Agency"]
            assert report["origin"] is None
            assert report["source"]["publisher"] == incident["source"]["publisher"]
            assert any(
                c["category"] == "fatalities" and c["value"] == "two"
                for c in report["claims"]
            )
        restored = await FileDiscoveryStore(tmp_path).read(identifier)
        assert tuple(r.article for r in restored.reports) == articles
    finally:
        await service.aclose()
