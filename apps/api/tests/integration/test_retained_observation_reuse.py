"""Repeated metadata can reuse a capture without inventing a fresh observation."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 11, 1, 9, tzinfo=UTC)
LEAD = NewsFeedItem(
    "first-route",
    "Daily News",
    "Flood killed two residents",
    "https://daily.example/report",
    None,
    None,
    NOW - timedelta(days=7),
)
ARTICLE = DiscoveryArticle(
    SourceReference(
        "publisher",
        LEAD.publisher,
        LEAD.title,
        LEAD.canonical_url,
        NOW - timedelta(days=7),
        None,
        NOW - timedelta(hours=1),
    ),
    "Two residents died in the flood. Rescuers reached the town.",
    indexed_at=LEAD.indexed_at,
)


async def index(store, scan, leads, *, now=NOW):
    interval = ReportingInterval.at_start(30, now)
    partition = CollectionPartition(
        "news", "hazard reporting", interval.start, interval.end, generation=scan
    )
    await store.attach(DiscoveryRun(scan, interval), (partition,), now=now, budget=1)
    work = await store.claim("search", "index", now=now)
    assert await store.commit_page(work, CollectionPage(leads=leads), now=now)


async def seed(path, *, lead=LEAD, article=ARTICLE, alternates=()):
    store = SQLiteCollectionJournal(path)
    await index(store, "before", (lead,))
    work = await store.claim("retrieve", "publisher", now=NOW)
    assert await store.commit_article(work, article, now=NOW, alternates=alternates)
    await store.finish_pass(now=NOW)
    return SQLiteCollectionJournal(path)


async def test_reopen_reuses_exact_capture_without_spending_request_or_fairness_turn(
    tmp_path,
):
    path = tmp_path / "collection.sqlite"
    store = await seed(path)
    novel = replace(LEAD, canonical_url="https://new.example/report")
    repeated = replace(LEAD, external_id="another-route", discovery_hint="flood theme")
    await index(store, "after", (repeated, novel))
    work = await store.claim("retrieve", "publisher", now=NOW)
    assert work.lead == novel
    view = await store.snapshot("after", now=NOW)
    assert view.articles == (ARTICLE,)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1
        assert (
            db.execute(
                "SELECT count(*) FROM attempts a JOIN work w ON w.id=a.work WHERE "
                "w.kind='retrieve'"
            ).fetchone()[0]
            == 2
        )
        assert db.execute("SELECT claimed FROM retrieval_rotation").fetchone()[0] == 2
        assert (
            db.execute(
                "SELECT remaining FROM pass_budget WHERE "
                "provider='article-retrieval' ORDER BY pass_id DESC LIMIT 1"
            ).fetchone()[0]
            == 3
        )
        assert (
            db.execute(
                "SELECT count(*) FROM work WHERE "
                "outcome='retained_article_reused' AND attempts=0"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "change",
    [
        {"indexed_at": NOW},
        {"updated_at": NOW},
        {"published_at": NOW},
        {"title": "Flood killed three residents"},
        {"search_title": "A changed native headline"},
        {"publisher": "Another publisher"},
    ],
)
async def test_changed_metadata_still_requests_a_new_capture(tmp_path, change):
    store = await seed(tmp_path / "collection.sqlite")
    changed = replace(LEAD, **change)
    await index(store, "after", (changed,))
    work = await store.claim("retrieve", "publisher", now=NOW)
    assert work is not None and work.lead == changed


@pytest.mark.parametrize(
    "article",
    [
        replace(ARTICLE, text=""),
        replace(ARTICLE, indexed_at=NOW),
        replace(
            ARTICLE,
            source=replace(ARTICLE.source, title="A different captured headline"),
        ),
        replace(
            ARTICLE,
            source=replace(ARTICLE.source, retrieved_at=NOW + timedelta(seconds=1)),
        ),
        replace(
            ARTICLE,
            source=replace(
                ARTICLE.source, retrieved_at=NOW - timedelta(days=1, seconds=1)
            ),
        ),
    ],
)
async def test_incompatible_or_expired_capture_does_not_prevent_a_request(
    tmp_path, article
):
    store = await seed(tmp_path / "collection.sqlite", article=article)
    await index(store, "after", (LEAD,))
    assert await store.claim("retrieve", "publisher", now=NOW) is not None


async def test_unknown_observation_time_does_not_suppress_refresh(tmp_path):
    unknown = replace(LEAD, indexed_at=None)
    store = await seed(
        tmp_path / "collection.sqlite",
        lead=unknown,
        article=replace(ARTICLE, indexed_at=None),
    )
    await index(store, "after", (unknown,))
    assert await store.claim("retrieve", "publisher", now=NOW) is not None


@pytest.mark.parametrize(
    "source",
    [
        replace(ARTICLE.source, published_at=None),
        replace(ARTICLE.source, publication_precision="unknown"),
    ],
)
async def test_unresolved_publication_can_refresh_and_keeps_the_old_capture(
    tmp_path, source
):
    unresolved = replace(ARTICLE, source=source)
    store = await seed(tmp_path / "collection.sqlite", article=unresolved)
    await index(store, "after", (LEAD,))
    work = await store.claim("retrieve", "publisher", now=NOW)
    assert work is not None and work.lead == LEAD
    refreshed = replace(ARTICLE, source=replace(ARTICLE.source, retrieved_at=NOW))
    assert await store.commit_article(work, refreshed, now=NOW)
    view = await store.snapshot("after", now=NOW)
    assert set(view.articles) == {unresolved, refreshed}


async def test_live_lease_is_not_replaced_by_retained_evidence(tmp_path):
    path = tmp_path / "collection.sqlite"
    store = await seed(path)
    await index(store, "after", (LEAD,))
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE work SET "
            "state='leased',token='other-worker',lease_until=? "
            "WHERE kind='retrieve' AND state='pending'",
            ((NOW + timedelta(minutes=1)).timestamp(),),
        )
    assert await store.claim("retrieve", "publisher", now=NOW) is None
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM work WHERE token='other-worker' AND "
                "state='leased'"
            ).fetchone()[0]
            == 1
        )


async def test_reuse_keeps_original_pending_followup_searches_accessible(tmp_path):
    interval = ReportingInterval.at_start(30, NOW)
    alternate = CollectionPartition(
        "alternate",
        "retained headline",
        interval.start,
        NOW,
        alternate_for=LEAD.canonical_url,
    )
    store = await seed(tmp_path / "collection.sqlite", alternates=(alternate,))
    await index(store, "after", (LEAD,))
    assert await store.claim("retrieve", "publisher", now=NOW) is None
    followup = await store.claim("search", "alternate", now=NOW, provider="alternate")
    assert followup is not None and followup.partition == alternate
    with sqlite3.connect(tmp_path / "collection.sqlite") as db:
        assert (
            db.execute(
                "SELECT count(*) FROM scan_work WHERE scan='after' AND work=?",
                (followup.work_id,),
            ).fetchone()[0]
            == 1
        )


async def test_newer_observation_keeps_both_capture_versions_and_reuses_exact_one(
    tmp_path,
):
    path = tmp_path / "collection.sqlite"
    store = await seed(path)
    changed = replace(LEAD, indexed_at=NOW)
    revised = replace(
        ARTICLE,
        text="Three residents died in the flood.",
        indexed_at=NOW,
        source=replace(ARTICLE.source, retrieved_at=NOW),
    )
    await index(store, "newer", (changed,))
    work = await store.claim("retrieve", "publisher", now=NOW)
    assert await store.commit_article(work, revised, now=NOW)
    await store.finish_pass(now=NOW)
    await index(store, "repeat-old", (LEAD,))
    assert await store.claim("retrieve", "publisher", now=NOW) is None
    view = await store.snapshot("repeat-old", now=NOW)
    assert set(view.articles) == {ARTICLE, revised}
    with sqlite3.connect(path) as db:
        row = db.execute(
            "SELECT e.article FROM work w JOIN work_evidence we ON we.work=w.id "
            "JOIN evidence e ON e.id=we.evidence "
            "WHERE w.outcome='retained_article_reused'"
        ).fetchone()
        assert b"Two residents" in row[0]
        assert db.execute("SELECT count(*) FROM evidence").fetchone()[0] == 2


async def test_network_host_cooldown_does_not_delay_retained_capture_reuse(tmp_path):
    path = tmp_path / "collection.sqlite"
    store = await seed(path)
    await index(store, "after", (LEAD,))
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT OR REPLACE INTO cooldowns(provider,until_time) VALUES(?,?)",
            ("publisher-host:daily.example", (NOW + timedelta(hours=1)).timestamp()),
        )
    assert await store.claim("retrieve", "publisher", now=NOW) is None
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM work WHERE outcome='retained_article_reused'"
            ).fetchone()[0]
            == 1
        )
