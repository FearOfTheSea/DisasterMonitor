"""Index hints order resolution without excluding weak or unfamiliar headlines."""

from datetime import UTC, datetime, timedelta

import httpx

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.news.google_news_collection import (
    GoogleNewsCollectionProvider,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
HEADLINES = (
    ("BACKGROUND", "New regional risk atlas published"),
    ("SPORT", "Football player dies following on-field collision"),
    ("RECOVERY", "Flood survivors mark anniversary of disaster"),
    ("FATAL", "Three people killed in overnight flood"),
    ("UNKNOWN", "Local families describe what happened last night"),
)


def response(request):
    items = "".join(
        f"<item><title>{title}</title>"
        f"<link>https://news.google.com/rss/articles/{identity}</link>"
        '<source url="https://daily.example">Regional Daily</source>'
        "<pubDate>Mon, 14 Sep 2026 12:00:00 GMT</pubDate></item>"
        for identity, title in HEADLINES
    )
    return httpx.Response(200, text=f"<rss><channel>{items}</channel></rss>")


async def test_resolution_orders_specific_disaster_reporting_and_retains_every_hint():
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider = GoogleNewsCollectionProvider(client=client, minimum_interval=0)
        root = CollectionPartition(
            provider.source_id, provider.queries[0], NOW - timedelta(days=1), NOW
        )
        page = await provider.fetch_page(root)
    assert [child.query for child in page.children] == [
        "google-article:FATAL",
        "google-article:SPORT",
        "google-article:RECOVERY",
        "google-article:BACKGROUND",
        "google-article:UNKNOWN",
    ]
    assert all(child.defer_initial_request for child in page.children)
    assert not page.articles and not page.leads


async def test_ranked_citation_reaches_journal_claim_and_survives_continuation(
    tmp_path,
):
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider = GoogleNewsCollectionProvider(client=client, minimum_interval=0)
        root = CollectionPartition(
            provider.source_id, provider.queries[0], NOW - timedelta(days=1), NOW
        )
        path = tmp_path / "journal.sqlite"
        journal = SQLiteCollectionJournal(path)
        await journal.attach(
            DiscoveryRun("ranked", ReportingInterval.at_start(1, NOW)),
            (root,),
            now=NOW,
            budget=20,
        )
        feed = await journal.claim("search", "feed", now=NOW)
        page = await provider.fetch_page(feed.partition)
        await journal.commit_page(feed, page, now=NOW)
        first = await journal.claim("search", "resolve", now=NOW)
        assert first.partition.query == "google-article:FATAL"
        await journal.commit_page(
            first, CollectionPage(next_cursor="public-page-continuation"), now=NOW
        )
        reopened = SQLiteCollectionJournal(path)
        continued = await reopened.claim("search", "finish", now=NOW)
        assert continued.work_id == first.work_id
        await reopened.commit_page(continued, CollectionPage(), now=NOW)
        remaining = []
        while work := await reopened.claim("search", "remaining", now=NOW):
            remaining.append(work.partition.query)
            await reopened.commit_page(work, CollectionPage(), now=NOW)
        assert remaining == [
            "google-article:SPORT",
            "google-article:RECOVERY",
            "google-article:BACKGROUND",
            "google-article:UNKNOWN",
        ]
