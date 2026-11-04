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


async def test_equal_strength_citations_use_index_recency_without_dropping_unknowns(
    tmp_path,
):
    entries = (
        ("OLD", "Mon, 14 Sep 2026 12:00:00 GMT"),
        ("UNKNOWN_A", None),
        ("NEW", "Tue, 15 Sep 2026 10:00:00 GMT"),
        ("OFFSET", "Tue, 15 Sep 2026 11:00:00 +0200"),
        ("TIED", "Tue, 15 Sep 2026 12:00:00 +0200"),
        ("UNKNOWN_B", None),
        ("WEAK", "Tue, 15 Sep 2026 11:00:00 GMT"),
    )

    def dated_response(request):
        items = "".join(
            "<item><title>"
            + (
                "Local families describe response"
                if key == "WEAK"
                else "Flood killed two"
            )
            + f"</title><link>https://news.google.com/rss/articles/{key}</link>"
            + '<source url="https://daily.example">Daily</source>'
            + (f"<pubDate>{stamp}</pubDate>" if stamp else "")
            + "</item>"
            for key, stamp in entries
        )
        return httpx.Response(200, text=f"<rss><channel>{items}</channel></rss>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(dated_response)
    ) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        page = await provider.fetch_page(
            CollectionPartition(
                provider.source_id, provider.queries[0], NOW - timedelta(days=1), NOW
            )
        )
    assert [c.query for c in page.children] == [
        "google-article:NEW",
        "google-article:TIED",
        "google-article:OFFSET",
        "google-article:OLD",
        "google-article:UNKNOWN_A",
        "google-article:UNKNOWN_B",
        "google-article:WEAK",
    ]
    assert not page.articles and not page.leads
    assert len(page.children) == len(entries)
    assert all(c.defer_initial_request and c.shared_resource for c in page.children)
    journal = SQLiteCollectionJournal(tmp_path / "recent.sqlite")
    root = CollectionPartition(
        provider.source_id, provider.queries[0], NOW - timedelta(days=1), NOW
    )
    await journal.attach(
        DiscoveryRun("recent", ReportingInterval.at_start(1, NOW)),
        (root,),
        now=NOW,
        budget=20,
    )
    work = await journal.claim("search", "feed", now=NOW)
    await journal.commit_page(work, page, now=NOW)
    selected = await journal.claim("search", "resolve", now=NOW)
    assert selected.partition.query == "google-article:NEW"
