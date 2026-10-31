"""Archive backfill, recent updates and frozen viewers share retained evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
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

NOW = datetime(2026, 10, 25, 7, tzinfo=UTC)
TARGET = NOW.replace(hour=0)
URL = "https://daily.example/flood"


def lead(url=URL):
    return NewsFeedItem("report", "Daily", "Flood kills two", url, None, None)


class Clock:
    now = NOW

    def __call__(self):
        return self.now


class Archive:
    source_id = "controlled-index"
    queries = ("hazard metadata",)
    supports_time_filter = True
    supports_alternates = False
    index_availability_delay = timedelta(minutes=15)

    def __init__(self):
        self.requests = []

    async def fetch_page(self, partition):
        self.requests.append(partition)
        return CollectionPage(
            leads=(lead(),) if partition.start <= TARGET < partition.end else ()
        )


class Reader:
    def __init__(self, clock):
        self.clock = clock
        self.requests = []

    async def retrieve(self, item):
        self.requests.append(item.canonical_url)
        return DiscoveryArticle(
            SourceReference(
                "news",
                "Daily",
                item.title,
                item.canonical_url,
                TARGET + timedelta(hours=1),
                None,
                self.clock(),
            ),
            "Flooding struck Riverton. Two people died.",
        )


async def test_closed_archive_and_publisher_evidence_survive_new_viewer_generation(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    clock, archive = Clock(), Archive()
    reader = Reader(clock)
    runtime = ResumableDiscovery(
        (archive,), reader, SQLiteCollectionJournal(path), clock=clock
    )
    first = await runtime.start(1)
    await runtime.wait(first.scan_id)
    assert len((await runtime.get(first.scan_id)).reports) == 1
    await runtime.aclose()

    # A different actual viewer interval and process must reuse completed
    # backfill while it schedules only new index windows.
    clock.now += timedelta(hours=7)
    restarted = ResumableDiscovery(
        (archive,), reader, SQLiteCollectionJournal(path), clock=clock
    )
    try:
        second = await restarted.start(1)
        await restarted.wait(second.scan_id)
        result = await restarted.get(second.scan_id)
        assert result.interval != first.interval
        assert len(result.reports) == 1
        assert result.reports[0].article.source.canonical_url == URL
        assert reader.requests == [URL]
        target_requests = [p for p in archive.requests if p.start <= TARGET < p.end]
        assert len(target_requests) == 1
    finally:
        await restarted.aclose()


async def test_continue_updates_recent_index_without_extending_publication_cutoff(
    tmp_path,
):
    clock = Clock()

    class RecentArchive(Archive):
        async def fetch_page(self, partition):
            self.requests.append(partition)
            if not partition.start <= NOW < partition.end:
                return CollectionPage()
            if clock() == NOW:
                return CollectionPage(next_cursor="retained-position")
            if partition.cursor:
                return CollectionPage()
            return CollectionPage(leads=(lead(), lead("https://daily.example/later")))

    class PublicationReader(Reader):
        async def retrieve(self, item):
            article = await super().retrieve(item)
            published = (
                NOW - timedelta(minutes=30)
                if item.canonical_url == URL
                else clock() - timedelta(minutes=30)
            )
            return replace(
                article, source=replace(article.source, published_at=published)
            )

    archive = RecentArchive()
    reader = PublicationReader(clock)
    runtime = ResumableDiscovery(
        (archive,),
        reader,
        SQLiteCollectionJournal(tmp_path / "journal.sqlite"),
        clock=clock,
        page_budget=1,
    )
    try:
        first = await runtime.start(1)
        await runtime.wait(first.scan_id)
        clock.now += timedelta(hours=2)
        continued = await runtime.continue_collection(first.scan_id)
        await runtime.wait(first.scan_id)
        # Continue may need several bounded passes to reach newly attached
        # windows behind existing work. Never raise the configured allowance.
        for _ in range(8):
            result = await runtime.get(first.scan_id)
            if len(reader.requests) == 2:
                break
            await runtime.continue_collection(first.scan_id)
            await runtime.wait(first.scan_id)
        result = await runtime.get(first.scan_id)
        assert result.interval == first.interval == continued.interval
        assert set(reader.requests) == {URL, "https://daily.example/later"}
        visible = {
            r.article.source.canonical_url for e in result.events for r in e.reports
        }
        assert URL in visible
        assert "https://daily.example/later" not in visible
    finally:
        await runtime.aclose()


@pytest.mark.parametrize("republished", [False, True])
async def test_refreshed_url_preserves_earlier_reporting_and_publication_cutoff(
    tmp_path, republished
):
    clock = Clock()

    class Feed:
        source_id = "controlled-rss"
        queries = ("flood",)
        supports_time_filter = False
        supports_alternates = False

        async def fetch_page(self, partition):
            return CollectionPage(leads=(lead(),))

    class RevisionReader(Reader):
        async def retrieve(self, item):
            article = await super().retrieve(item)
            refreshed = clock() > NOW
            return replace(
                article,
                source=replace(
                    article.source,
                    published_at=clock() - timedelta(hours=1)
                    if refreshed and republished
                    else NOW - timedelta(hours=1),
                    updated_at=clock() if refreshed else None,
                ),
                text="Flooding struck Riverton on 25 October 2026. "
                + ("Three" if refreshed else "Two")
                + " people died.",
            )

    reader = RevisionReader(clock)
    runtime = ResumableDiscovery(
        (Feed(),),
        reader,
        SQLiteCollectionJournal(tmp_path / "journal.sqlite"),
        clock=clock,
    )
    try:
        original = await runtime.start(1)
        await runtime.wait(original.scan_id)
        clock.now += timedelta(hours=7)
        await runtime.continue_collection(original.scan_id)
        await runtime.wait(original.scan_id)
        result = await runtime.get(original.scan_id)
        assert reader.requests == [URL, URL]
        assert result.interval == original.interval
        assert len(result.reports) == 2
        values = {
            claim.fact.value.casefold()
            for event in result.events
            for report in event.reports
            for claim in report.mention.claims
            if claim.fact.category == "fatalities"
        }
        assert "two" in values
        assert ("three" in values) == (not republished)
        if republished:
            assert any(r.eligibility == "outside_interval" for r in result.reports)
    finally:
        await runtime.aclose()


@pytest.mark.parametrize("already_leased", [False, True])
async def test_refresh_generation_keeps_cursor_and_honors_an_inflight_page(
    tmp_path, already_leased
):
    before = NOW.replace(hour=11, minute=59)
    after = before + timedelta(minutes=1)
    journal = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    interval = ReportingInterval.at_start(1, before)
    partition = CollectionPartition(
        "index",
        "hazards",
        interval.start,
        interval.end,
        generation="stable-index",
        retrieval_generation="observation-before",
    )
    await journal.attach(
        DiscoveryRun("first", interval), (partition,), now=before, budget=10
    )
    page = await journal.claim("search", "first", now=before)
    assert await journal.commit_page(
        page, CollectionPage(leads=(lead(),), next_cursor="retained-cursor"), now=before
    )
    article_work = await journal.claim("retrieve", "first-reader", now=before)
    article = DiscoveryArticle(
        SourceReference("news", "Daily", "Flood", URL, before, None, before),
        "Flooding struck Riverton. Two people died.",
    )
    assert await journal.commit_article(article_work, article, now=before)
    leased = (
        await journal.claim("search", "inflight", now=before)
        if already_leased
        else None
    )
    refreshed = replace(partition, retrieval_generation="observation-after")
    await journal.attach(
        DiscoveryRun("second", ReportingInterval.at_start(1, after)),
        (refreshed,),
        now=after,
        budget=10,
    )
    page = leased or await journal.claim("search", "new", now=after)
    assert page.partition.cursor == "retained-cursor"
    assert await journal.commit_page(page, CollectionPage(leads=(lead(),)), now=after)
    # The newly announced URL must refresh in the new generation even when its
    # metadata request was already in flight. The old capture remains retained.
    refreshed_article = await journal.claim("retrieve", "new-reader", now=after)
    assert refreshed_article is not None
    assert refreshed_article.lead.canonical_url == URL
    snapshot = await journal.snapshot("second", now=after)
    assert snapshot.articles == (article,)
