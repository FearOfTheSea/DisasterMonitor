"""Citation expansion shares resources and balances source queries and windows."""

from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def root(family, week):
    start = NOW - timedelta(days=14 - week * 7)
    return CollectionPartition(
        "index", family, start, start + timedelta(days=7), generation="controlled"
    )


def citation(parent, identity):
    return replace(
        parent,
        query=identity,
        depth=1,
        cursor="public-page",
        defer_initial_request=True,
        shared_resource=True,
    )


def test_only_explicit_shared_resources_ignore_weekly_search_bounds():
    first, second = root("broad", 0), root("broad", 1)
    assert first.key != second.key
    assert citation(first, "opaque").key == citation(second, "opaque").key
    assert (
        citation(first, "opaque").key
        != replace(citation(second, "opaque"), generation="next-refresh").key
    )
    with pytest.raises(ValueError):
        replace(first, shared_resource=True)


async def test_citation_expansion_balances_queries_and_weeks_across_restart_and_passes(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path, maximum_metadata_requests=100)
    roots = tuple(root(f, w) for f in ("quake", "rain", "dry") for w in (0, 1))
    run = DiscoveryRun("view", ReportingInterval.at_start(30, NOW))
    await store.attach(run, roots, now=NOW, budget=10)
    # Hold index responses until all roots are leased, isolating citation-family
    # and publication-window fairness from index/resolution interleaving.
    feeds = [await store.claim("search", "feed", now=NOW) for _ in roots]
    for work in feeds:
        parent = work.partition
        assert not parent.defer_initial_request
        children = tuple(
            citation(parent, f"{parent.query}|{parent.start.isoformat()}|{i}")
            for i in range(8)
        )
        assert await store.commit_page(work, CollectionPage(children=children), now=NOW)
    selected = []
    for batch in range(3):
        if batch:
            store = SQLiteCollectionJournal(path, maximum_metadata_requests=100)
            await store.continue_scan(run.scan_id, now=NOW, budget=4)
        for _ in range(2):
            work = await store.claim("search", "page", now=NOW)
            selected.append(work.partition.query.split("|")[:2])
            assert await store.commit_page(
                work, CollectionPage(next_cursor="resolution"), now=NOW
            )
            continued = await store.claim("search", "finish-page", now=NOW)
            assert continued.work_id == work.work_id
            assert await store.commit_page(continued, CollectionPage(), now=NOW)
        assert await store.claim("search", "no-extra", now=NOW) is None
        await store.finish_pass(now=NOW)
    assert Counter(row[0] for row in selected) == {"quake": 2, "rain": 2, "dry": 2}
    assert sorted(Counter(row[1] for row in selected).values()) == [3, 3]


async def test_reused_resource_keeps_one_resolution_and_links_later_viewer_to_publisher(
    tmp_path,
):
    store = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    first = root("broad", 0)
    await store.attach(
        DiscoveryRun("first", ReportingInterval.at_start(30, NOW)),
        (first,),
        now=NOW,
        budget=20,
    )
    feed = await store.claim("search", "feed", now=NOW)
    child = citation(first, "opaque-id")
    await store.commit_page(feed, CollectionPage(children=(child,)), now=NOW)
    resolve = await store.claim("search", "resolve", now=NOW)
    lead = NewsFeedItem(
        "one", "Daily", "Recovery report", "https://daily.example/story", None, None
    )
    await store.commit_page(resolve, CollectionPage(leads=(lead,)), now=NOW)
    second = root("another-query", 1)
    await store.attach(
        DiscoveryRun("second", ReportingInterval.at_start(30, NOW)),
        (second,),
        now=NOW,
        budget=20,
    )
    feed = await store.claim("search", "new-feed", now=NOW)
    assert feed.partition.query == "another-query"
    await store.commit_page(
        feed, CollectionPage(children=(citation(second, "opaque-id"),)), now=NOW
    )
    assert await store.claim("search", "no-replayed-resource", now=NOW) is None
    snapshot = await store.snapshot("second", now=NOW)
    assert snapshot.leads == (lead,)
    assert snapshot.progress.leads_acquired == 1


async def test_legacy_unstarted_citations_migrate_without_changing_keys_or_attempts(
    tmp_path,
):
    import sqlite3

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    parents = (root("one", 0), root("two", 1))
    await store.attach(
        DiscoveryRun("legacy", ReportingInterval.at_start(30, NOW)),
        parents,
        now=NOW,
        budget=20,
    )
    for parent in parents:
        work = await store.claim("search", "feed", now=NOW)
        children = tuple(
            replace(citation(parent, f"{parent.query}-{i}"), shared_resource=False)
            for i in range(3)
        )
        await store.commit_page(work, CollectionPage(children=children), now=NOW)
    with sqlite3.connect(path) as db:
        before = db.execute(
            "SELECT id,payload,attempts FROM work ORDER BY id"
        ).fetchall()
        db.execute("DROP TABLE citation_work")
        db.execute("DROP TABLE citation_lanes")
    migrated = SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT id,payload,attempts FROM work ORDER BY id").fetchall()
            == before
        )
    first = await migrated.claim("search", "first", now=NOW)
    await migrated.commit_page(first, CollectionPage(), now=NOW)
    second = await migrated.claim("search", "second", now=NOW)
    assert first.partition.query.split("-")[0] != second.partition.query.split("-")[0]


async def test_shared_google_metadata_identity_deduplicates_overlapping_feed_windows():
    import httpx

    from disaster_monitor.infrastructure.news.google_news_collection import (
        GoogleNewsCollectionProvider,
    )

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            text="<rss><channel><item><title>Recovery continues</title>"
            "<link>https://news.google.com/rss/articles/CBMi_TEST</link>"
            '<source url="https://daily.example">Daily</source>'
            "</item></channel></rss>",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        first = replace(root(provider.queries[0], 0), provider=provider.source_id)
        second = replace(root(provider.queries[1], 1), provider=provider.source_id)
        left = (await provider.fetch_page(first)).children[0]
        right = (await provider.fetch_page(second)).children[0]
        assert left.key == right.key and left.shared_resource and right.shared_resource
        assert left.start != right.start
    assert len(requests) == 2


async def test_failed_legacy_migration_rolls_back_schema_and_can_be_retried(tmp_path):
    import sqlite3

    from pydantic import ValidationError

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    parent = root("one", 0)
    await store.attach(
        DiscoveryRun("legacy", ReportingInterval.at_start(30, NOW)),
        (parent,),
        now=NOW,
        budget=20,
    )
    feed = await store.claim("search", "feed", now=NOW)
    child = citation(parent, "opaque")
    await store.commit_page(feed, CollectionPage(children=(child,)), now=NOW)
    with sqlite3.connect(path) as db:
        retained = db.execute(
            "SELECT payload FROM work WHERE id=?", (child.key,)
        ).fetchone()[0]
        db.execute("DROP TABLE citation_work")
        db.execute("DROP TABLE citation_lanes")
        db.execute(
            "UPDATE work SET payload=? WHERE id=?",
            ('{"defer_initial_request":true}', child.key),
        )
    with pytest.raises(ValidationError):
        SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='citation_lanes'"
        ).fetchone()
        db.execute("UPDATE work SET payload=? WHERE id=?", (retained, child.key))
    reopened = SQLiteCollectionJournal(path)
    work = await reopened.claim("search", "recovered", now=NOW)
    assert work.work_id == child.key and work.attempts == 1
