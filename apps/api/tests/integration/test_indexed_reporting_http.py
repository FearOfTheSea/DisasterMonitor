"""Index-only evidence remains inspectable without acquisition or article promotion."""

import base64
import json
import sqlite3
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from disaster_monitor.application.incidents.indexed_reporting import (
    IndexedReportingQueries,
)
from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)
from disaster_monitor.infrastructure.operations.sqlite_indexed_reporting import (
    SQLiteIndexedReportingReader,
)
from disaster_monitor.presentation.http.api import create_schema_app

NOW = datetime(2026, 10, 31, tzinfo=UTC)


async def seed(store, run, query, items, *, provider="index", at=NOW):
    partition = CollectionPartition(provider, query, NOW - timedelta(days=7), NOW)
    if await store.read(run.scan_id) is None:
        await store.attach(run, (partition,), now=at, budget=200)
    else:
        await store.continue_scan(
            run.scan_id, partitions=(partition,), now=at, budget=200
        )
    work = await store.claim("search", "test", now=at, provider=provider)
    assert work is not None
    assert await store.commit_page(work, CollectionPage(leads=tuple(items)), now=at)


@pytest.fixture
async def retained(tmp_path):
    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, NOW))
    other = replace(run, scan_id=str(uuid4()))
    item = NewsFeedItem(
        "entry",
        "Local Daily",
        "Éboulement meurtrier près du village",
        "https://daily.example/report",
        None,
        None,
        NOW,
        "Three people died. <script>literal text</script>",
    )
    await seed(
        store,
        run,
        "first",
        [replace(item, canonical_url=f"https://daily.example/{n}") for n in range(53)],
    )
    await seed(
        store,
        other,
        "other",
        [replace(item, title="Other scan private entry")],
        provider="other-index",
    )
    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(
        indexed_reporting=IndexedReportingQueries(SQLiteIndexedReportingReader(path))
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, store, run, other, path, item


async def test_literal_index_wording_and_unicode_search_do_not_require_article_capture(
    retained,
):
    client, _, run, _, path, _ = retained
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
    response = await client.get(
        f"/api/v1/discovery-scans/{run.scan_id}/indexed-reporting",
        params={"query": "ÉBOULEMENT"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 25 and body["next_cursor"]
    item = body["items"][0]
    assert item["publisher"] == "Local Daily"
    assert item["index_excerpt"] == "Three people died. <script>literal text</script>"
    assert item["published_at"] is None and item["updated_at"] is None
    assert item["indexed_at"] == item["observed_at"] == "2026-10-31T00:00:00Z"
    assert (
        "capture_id" not in item and "fatalities" not in item and "event_id" not in item
    )
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before
        assert db.execute("select count(*) from evidence").fetchone()[0] == 0


async def test_continuation_keeps_page_and_membership_fences_when_new_work_is_attached(
    retained,
):
    client, store, run, other, _, item = retained
    url = f"/api/v1/discovery-scans/{run.scan_id}/indexed-reporting"
    first = (await client.get(url)).json()
    # Both a new page and an already-retained page attached later must stay outside
    # the original read snapshot, even though their headline would match.
    await seed(
        store,
        run,
        "later",
        [replace(item, title="Later observation")],
        provider="later-index",
        at=NOW + timedelta(seconds=1),
    )
    await store.continue_scan(
        run.scan_id,
        partitions=(
            CollectionPartition("other-index", "other", NOW - timedelta(days=7), NOW),
        ),
        now=NOW + timedelta(seconds=2),
        budget=200,
    )
    pages = [first]
    while pages[-1]["next_cursor"]:
        response = await client.get(url, params={"cursor": pages[-1]["next_cursor"]})
        assert response.status_code == 200
        pages.append(response.json())
    observations = [item for page in pages for item in page["items"]]
    assert [len(page["items"]) for page in pages] == [25, 25, 3]
    assert all(page["snapshot"] == first["snapshot"] for page in pages)
    assert len({row["observation_id"] for row in observations}) == 53
    assert all(row["title"] == item.title for row in observations)
    refreshed = (await client.get(url)).json()
    assert refreshed["snapshot"] != first["snapshot"]
    assert {row["title"] for row in refreshed["items"]} >= {
        "Later observation",
        "Other scan private entry",
    }


async def test_mutable_lead_replacement_cannot_rewrite_index_observation(retained):
    client, _, run, _, path, item = retained
    with sqlite3.connect(path) as db:
        db.execute(
            "update leads set lead=?",
            (
                json.dumps(
                    asdict(replace(item, title="Replaced current lead")), default=str
                ),
            ),
        )
    response = await client.get(
        f"/api/v1/discovery-scans/{run.scan_id}/indexed-reporting"
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["title"] == item.title


async def test_repeated_urls_and_unverified_themes_remain_separate_index_observations(
    retained,
):
    client, store, run, _, _, item = retained
    observed = replace(
        item,
        discovery_hint="landslide; death-related index theme (unverified)",
        search_title="Untrusted index wording",
        published_at=NOW - timedelta(days=20),
    )
    await seed(store, run, "repeated", [observed, observed], provider="second-index")
    response = await client.get(
        f"/api/v1/discovery-scans/{run.scan_id}/indexed-reporting",
        params={"query": "unverified"},
    )
    body = response.json()
    assert response.status_code == 200 and len(body["items"]) == 2
    assert body["items"][0]["canonical_url"] == body["items"][1]["canonical_url"]
    assert body["items"][0]["observation_id"] != body["items"][1]["observation_id"]
    assert body["items"][0]["search_wording"] == "Untrusted index wording"
    assert body["items"][0]["published_at"] == "2026-10-11T00:00:00Z"


async def test_scan_scope_empty_search_and_unknown_scan_are_distinct(retained):
    client, _, run, other, _, _ = retained
    url = f"/api/v1/discovery-scans/{run.scan_id}/indexed-reporting"
    empty = await client.get(url, params={"query": "Other scan private entry"})
    assert empty.status_code == 200 and empty.json()["items"] == []
    assert empty.json()["next_cursor"] is None
    other_body = (
        await client.get(f"/api/v1/discovery-scans/{other.scan_id}/indexed-reporting")
    ).json()
    assert len(other_body["items"]) == 1
    assert (
        await client.get(f"/api/v1/discovery-scans/{uuid4()}/indexed-reporting")
    ).status_code == 404


async def test_cursor_is_bound_to_scan_query_and_bounded_integer_positions(retained):
    client, _, run, other, _, _ = retained
    url = f"/api/v1/discovery-scans/{run.scan_id}/indexed-reporting"
    cursor = (await client.get(url)).json()["next_cursor"]
    assert (
        await client.get(url, params={"query": "changed", "cursor": cursor})
    ).status_code == 422
    assert (
        await client.get(
            f"/api/v1/discovery-scans/{other.scan_id}/indexed-reporting",
            params={"cursor": cursor},
        )
    ).status_code == 422
    for raw in (
        "[]",
        "null",
        json.dumps([run.scan_id, "", True, 1, 1, 0]),
        json.dumps([run.scan_id, "", 2**100, 1, 1, 0]),
    ):
        forged = base64.urlsafe_b64encode(raw.encode()).decode()
        assert (await client.get(url, params={"cursor": forged})).status_code == 422
    assert (await client.get(url, params={"query": "x" * 201})).status_code == 422


async def test_first_page_work_is_bounded_with_a_large_unretrieved_queue(
    tmp_path, monkeypatch
):
    from disaster_monitor.infrastructure.operations import sqlite_indexed_reporting

    path = tmp_path / "large.sqlite"
    store = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, NOW))
    item = NewsFeedItem(
        "entry", "Daily", "Source account", "https://daily.example/entry", None, None
    )
    for page in range(100):
        await seed(
            store,
            run,
            f"page-{page}",
            [
                replace(item, canonical_url=f"https://daily.example/{page}/{n}")
                for n in range(30)
            ],
        )
    connect = sqlite3.connect
    steps = 0

    def bounded_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)

        def progress():
            nonlocal steps
            steps += 1000
            return int(steps > 1_000_000)

        connection.set_progress_handler(progress, 1000)
        return connection

    monkeypatch.setattr(sqlite_indexed_reporting.sqlite3, "connect", bounded_connection)
    queries = IndexedReportingQueries(SQLiteIndexedReportingReader(path))
    page = await queries.read(run.scan_id)
    assert len(page.observations) == 25 and page.next_cursor
    # SQLite VM work bounds avoid machine-speed timing assertions. Metadata reads
    # must not multiply the pending article queue by the retained page count.
    assert steps <= 1_000_000
