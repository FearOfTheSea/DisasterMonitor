"""Identical observations keep their exact addresses without inflating projections."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.discovery_report_versions import (
    assess_article_versions,
)
from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.application.incidents.retained_reporting import (
    reporting_capture_id,
)
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)
from disaster_monitor.infrastructure.operations.sqlite_reporting_captures import (
    SQLiteReportingCaptureReader,
)
from disaster_monitor.presentation.http.api import create_schema_app

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
TEXT = "Floods struck Riverton. Two people died. " + "Retained context. 😀 " * 300


def article():
    return DiscoveryArticle(
        SourceReference(
            "news",
            "Daily",
            "Flood kills two",
            "https://daily.example/flood",
            NOW - timedelta(days=1),
            None,
            NOW,
        ),
        TEXT,
        bylines=("Original reporter",),
        origin="Shared wire",
        original_url="https://wire.example/flood",
    )


@pytest.fixture
async def retained(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path)
    original = article()
    observed = replace(
        original,
        source=replace(
            original.source, retrieved_at=NOW + timedelta(hours=1), snapshot_id="new"
        ),
        indexed_at=NOW + timedelta(hours=1),
    )
    revised = replace(original, text="Correction: the flood killed three people.")
    foreign = replace(
        original,
        source=replace(original.source, canonical_url="https://other.example/flood"),
    )
    capture_run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, NOW))
    partition = CollectionPartition("index", "news", capture_run.interval.start, NOW)
    await journal.attach(capture_run, (partition,), now=NOW, budget=10)
    work = await journal.claim("search", "test", now=NOW)
    assert work is not None
    assert await journal.commit_page(
        work, CollectionPage(articles=(original, observed, revised, foreign)), now=NOW
    )
    await journal.finish_pass(now=NOW)
    reports = await assess_article_versions(
        (original, observed), (), capture_run.interval, country_names=frozenset()
    )
    assert len(reports) == 1 and reports[0].article == observed
    run = replace(
        capture_run, status="completed", reports=reports, events=group_reports(reports)
    )
    await journal.save(run)
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(
        discovery_scans=DiscoveryScanService(
            (), journal, capture_reader=SQLiteReportingCaptureReader(path)
        ),
        active_incidents=ActiveIncidentsService(
            ProviderRegistry(()),
            country_catalog=StaticCountryCatalog(),
            discovery_store=journal,
            capture_reader=SQLiteReportingCaptureReader(path),
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http, path, run, original, observed, revised, foreign


def endpoints(run):
    return (
        f"/api/v1/discovery-scans/{run.scan_id}/reporting/",
        f"/api/v1/incidents/discovery:{run.scan_id}:{run.events[0].event_id}/reporting/",
    )


async def test_old_capture_survives_identical_recapture_with_original_attribution(
    retained,
):
    http, path, run, original, observed, _, _ = retained
    old_id, new_id = map(reporting_capture_id, (original, observed))
    assert old_id != new_id
    for endpoint in endpoints(run):
        text, offset = "", 0
        while True:
            response = await http.get(endpoint + old_id, params={"offset": offset})
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["capture_id"] == old_id
            assert page["source"]["retrieved_at"] == NOW.isoformat().replace(
                "+00:00", "Z"
            )
            assert page["source"]["snapshot_id"] is None
            assert page["bylines"] == ["Original reporter"]
            assert page["origin"] == "Shared wire"
            assert page["original_url"] == "https://wire.example/flood"
            text += page["text"]
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        assert text == TEXT
        latest = await http.get(endpoint + new_id)
        assert latest.status_code == 200
        assert latest.json()["source"]["snapshot_id"] == "new"
    reopened = SQLiteCollectionJournal(path)
    assert await reopened.read(run.scan_id) == run
    assert (
        await SQLiteReportingCaptureReader(path).read_capture(
            old_id, canonical_urls=(original.source.canonical_url,)
        )
        == original
    )


async def test_archive_does_not_alias_changed_text_or_foreign_reporting(retained):
    http, _, run, _, _, revised, foreign = retained
    for endpoint in endpoints(run):
        for capture in (
            reporting_capture_id(revised),
            reporting_capture_id(foreign),
            "unknown",
        ):
            assert (await http.get(endpoint + capture)).status_code == 404


async def test_old_capture_offset_validation_and_missing_owner_remain_explicit(
    retained,
):
    http, _, run, original, *_ = retained
    for endpoint in endpoints(run):
        url = endpoint + reporting_capture_id(original)
        assert (
            await http.get(url, params={"offset": len(TEXT) + 1})
        ).status_code == 422
        assert (
            await http.get(url.replace(run.scan_id, str(uuid4())))
        ).status_code == 404


@pytest.mark.parametrize("change", ["text", "byline", "origin", "publication", "title"])
async def test_same_url_different_account_cannot_own_an_archived_capture(
    retained, change
):
    http, path, run, original, observed, *_ = retained
    changed = {
        "text": replace(observed, text="Corrected reporting."),
        "byline": replace(observed, bylines=("Different author",)),
        "origin": replace(observed, origin="Different origin"),
        "publication": replace(
            observed, source=replace(observed.source, published_at=NOW)
        ),
        "title": replace(
            observed, source=replace(observed.source, title="Different headline")
        ),
    }[change]
    reports = tuple(replace(report, article=changed) for report in run.reports)
    different = replace(
        run,
        reports=reports,
        events=tuple(replace(event, reports=reports) for event in run.events),
    )
    await SQLiteCollectionJournal(path).save(different)
    for endpoint in endpoints(run):
        assert (
            await http.get(endpoint + reporting_capture_id(original))
        ).status_code == 404


async def test_old_journal_adds_lookup_index_without_changing_any_retained_rows(
    retained,
):
    _, path, run, original, *_ = retained
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT id,article FROM evidence ORDER BY id").fetchall()
        db.execute("DROP INDEX evidence_publisher_url")
    reopened = SQLiteCollectionJournal(path)
    assert (
        await SQLiteReportingCaptureReader(path).read_capture(
            reporting_capture_id(original),
            canonical_urls=(original.source.canonical_url,),
        )
        == original
    )
    assert await reopened.read(run.scan_id) == run
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT id,article FROM evidence ORDER BY id").fetchall()
            == before
        )
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT article FROM evidence WHERE "
            "json_extract(article, '$.source.canonical_url') IN (?)",
            (original.source.canonical_url,),
        ).fetchall()
        assert any("evidence_publisher_url" in str(row) for row in plan)
    assert (
        await SQLiteReportingCaptureReader(path).read_capture(
            reporting_capture_id(original), canonical_urls=()
        )
        is None
    )
