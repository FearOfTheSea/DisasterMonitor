"""Rolling views reuse publisher evidence even when its discovery feed changes."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


def article(published=NOW - timedelta(days=2), *, precision="exact", text=None):
    return DiscoveryArticle(
        SourceReference(
            "news",
            "Publisher",
            "Flood kills two in Riverton",
            "https://publisher.example/flood",
            published,
            None,
            NOW,
            publication_precision=precision,
        ),
        text or "Flooding struck Riverton. Two people died in the flood.",
        indexed_at=NOW,
        origin="Reporting agency",
        original_url="https://agency.example/flood",
        bylines=("Reporter One",),
    )


class Clock:
    now = NOW

    def __call__(self):
        return self.now


class ChangingFeed:
    source_id = "changing-rss"
    queries = ("flood deaths",)
    supports_time_filter = False
    supports_alternates = False

    def __init__(self):
        self.calls = 0

    async def fetch_page(self, partition):
        self.calls += 1
        return CollectionPage(
            leads=(
                NewsFeedItem(
                    "one",
                    "Publisher",
                    "Flood kills two in Riverton",
                    "https://publisher.example/flood",
                    None,
                    None,
                ),
            )
            if self.calls == 1
            else ()
        )


class Reader:
    calls = 0

    async def retrieve(self, lead):
        self.calls += 1
        return article()


async def test_new_scan_keeps_qualifying_report_after_it_leaves_the_rss_feed(tmp_path):
    clock, feed, reader = Clock(), ChangingFeed(), Reader()
    service = ResumableDiscovery(
        (feed,),
        reader,
        SQLiteCollectionJournal(tmp_path / "journal.sqlite"),
        clock=clock,
    )
    try:
        first = await service.start(7)
        await service.wait(first.scan_id)
        assert len((await service.get(first.scan_id)).events) == 1
        clock.now += timedelta(hours=7)
        second = await service.start(7)
        await service.wait(second.scan_id)
        current = await service.get(second.scan_id)
        assert feed.calls == 2
        assert reader.calls == 1
        assert len(current.events) == 1
        assert current.events[0].reports[0].article == article()
        assert current.interval == ReportingInterval.at_start(7, clock.now)
        assert (await service.get(first.scan_id)).interval == first.interval
    finally:
        await service.aclose()


async def store_articles(journal, records):
    original = DiscoveryRun("original", ReportingInterval.at_start(30, NOW))
    partition = CollectionPartition("index", "reports", original.interval.start, NOW)
    await journal.attach(original, (partition,), now=NOW, budget=10)
    work = await journal.claim("search", "index", now=NOW)
    assert work is not None
    assert await journal.commit_page(work, CollectionPage(articles=records), now=NOW)
    await journal.finish_pass(now=NOW)


async def test_retained_selection_uses_publication_not_event_or_update_time(tmp_path):
    journal = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    inside = article(NOW - timedelta(hours=12))
    old = replace(
        article(NOW - timedelta(days=3)),
        source=replace(article(NOW - timedelta(days=3)).source, updated_at=NOW),
        text="Earlier account. Two people died in the flood.",
        event_time=NOW,
    )
    future = article(NOW + timedelta(seconds=1), text="Later publication.")
    day = article(
        NOW - timedelta(days=1), precision="day", text="Day precision account."
    )
    await store_articles(journal, (inside, old, future, day))
    current = DiscoveryRun("new", ReportingInterval.at_start(1, NOW))
    await journal.attach(current, (), now=NOW, budget=1)
    snapshot = await journal.snapshot(current.scan_id, now=NOW)
    assert set(snapshot.articles) == {inside, day}
    assert snapshot.progress.articles_retrieved == 2
    original = await journal.snapshot("original", now=NOW)
    assert set(original.articles) == {inside, old, future, day}
    # A publication day overlapping the start stays uncertain, not exact-date evidence.
    assert assess_article(day, current.interval).eligibility == "uncertain_publication"


async def test_undated_retained_candidates_keep_observation_and_publication_separate(
    tmp_path,
):
    journal = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    recent = article(None)
    stale = replace(
        recent,
        source=replace(recent.source, retrieved_at=NOW - timedelta(days=3)),
        indexed_at=NOW - timedelta(days=3),
        text="An older undated account.",
    )
    future = replace(
        recent,
        source=replace(recent.source, retrieved_at=NOW + timedelta(hours=1)),
        indexed_at=NOW + timedelta(hours=1),
        text="An observation after the cutoff.",
    )
    await store_articles(journal, (recent, stale, future))
    current = DiscoveryRun("new", ReportingInterval.at_start(1, NOW))
    await journal.attach(current, (), now=NOW, budget=1)
    snapshot = await journal.snapshot(current.scan_id, now=NOW)
    assert snapshot.articles == (recent,)
    assert snapshot.articles[0].source.published_at is None


async def test_existing_journal_reuses_versions_after_restart_without_new_acquisition(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path)
    first = article()
    revised = replace(
        first, text="Three people died in the flood.", bylines=("Reporter Two",)
    )
    await store_articles(journal, (first, revised))
    with sqlite3.connect(path) as db:
        before = {
            t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
            for t in ("evidence", "attempts", "pages", "work")
        }
    restarted = SQLiteCollectionJournal(path)
    current = DiscoveryRun("new", ReportingInterval.at_start(7, NOW))
    await restarted.attach(current, (), now=NOW, budget=1)
    snapshot = await restarted.snapshot(current.scan_id, now=NOW)
    assert set(snapshot.articles) == {first, revised}
    assert {a.bylines for a in snapshot.articles} == {
        ("Reporter One",),
        ("Reporter Two",),
    }
    assert all(a.origin == "Reporting agency" for a in snapshot.articles)
    assert all(
        a.original_url == "https://agency.example/flood" for a in snapshot.articles
    )
    with sqlite3.connect(path) as db:
        after = {
            t: db.execute("SELECT COUNT(*) FROM " + t).fetchone()[0] for t in before
        }
    assert after == before
