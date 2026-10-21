"""Open public RSS leads stay separate from publisher evidence and window admission."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.application.incidents.collection_planning import plan_collection
from disaster_monitor.domain.collection import (
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import ReportingInterval
from disaster_monitor.infrastructure.news.bing_collection import (
    BingRssCollectionProvider,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
RSS = b"""<rss xmlns:News="https://www.bing.com/news/search"><channel><item>
<title>Floods hit Lakeview</title>
<link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Funlisted.example%2Fstory</link>
<pubDate>Sun, 18 Oct 2026 14:07:13 GMT</pubDate>
<News:Source>Regional Daily</News:Source>
<description>Officials report two deaths.</description></item></channel></rss>"""


async def test_open_publisher_lead_does_not_promote_feed_clock_or_snippet():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        part = CollectionPartition(
            provider.source_id, "flood", NOW - timedelta(days=1), NOW
        )
        page = await provider.fetch_page(part)
    assert len(calls) == 1
    assert calls[0].url.params["format"] == "rss"
    assert calls[0].url.params["qft"] == 'interval="9" sortbydate="1"'
    (lead,) = page.leads
    assert lead.canonical_url == "https://unlisted.example/story"
    assert lead.publisher == "Regional Daily"
    assert lead.published_at is None
    assert lead.indexed_at == datetime(2026, 10, 18, 14, 7, 13, tzinfo=UTC)
    assert not page.articles
    assert page.saturated
    assert page.requested_start is None  # This endpoint cannot filter history.
    assert page.next_cursor == "relevance"
    assert any("historical" in notice for notice in page.notices)


async def test_recent_then_relevance_feed_pages_share_one_provider_and_resume_cursor(
    tmp_path,
):
    from uuid import uuid4

    from disaster_monitor.domain.discovery import DiscoveryRun
    from disaster_monitor.infrastructure.operations.sqlite_collection import (
        SQLiteCollectionJournal,
    )

    calls = []

    def respond(request):
        qft = request.url.params["qft"]
        calls.append(qft)
        content = RSS if "sortbydate" in qft else RSS.replace(b"%2Fstory", b"%2Fother")
        return httpx.Response(200, content=content)

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(30, NOW))
    partition = CollectionPartition(
        "bing-rss-discovery", "flood", NOW - timedelta(days=1), NOW
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        await store.attach(run, (partition,), now=NOW, budget=1)
        first = await store.claim("search", "first", now=NOW)
        recent = await provider.fetch_page(first.partition)
        assert recent.next_cursor == "relevance"
        assert await store.commit_page(first, recent, now=NOW)
        await store.finish_pass(now=NOW)
        assert (
            await store.snapshot(run.scan_id, now=NOW)
        ).progress.searches_pending == 1
        restarted = SQLiteCollectionJournal(path)
        await restarted.continue_scan(run.scan_id, now=NOW, budget=1)
        second = await restarted.claim("search", "second", now=NOW)
        assert second.partition.cursor == "relevance"
        relevant = await provider.fetch_page(second.partition)
        assert relevant.next_cursor is None and relevant.saturated
        assert await restarted.commit_page(second, relevant, now=NOW)
        progress = (await restarted.snapshot(run.scan_id, now=NOW)).progress
        assert progress.leads_acquired == 2
        assert progress.pages_acquired == 2
        assert progress.searches_saturated == 1
    assert calls == ['interval="9" sortbydate="1"', 'interval="9"']


async def test_unknown_rss_continuation_is_rejected_without_a_provider_request():
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, content=RSS)
        )
    ) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        with pytest.raises(CollectionProviderError, match="continuation"):
            await provider.fetch_page(
                CollectionPartition(
                    provider.source_id,
                    "flood",
                    NOW - timedelta(days=1),
                    NOW,
                    cursor="https://untrusted.example/next",
                )
            )
    assert not requests


async def test_inaccessible_article_can_use_one_bing_alternate_without_recursion():
    from dataclasses import replace

    from disaster_monitor.application.incidents.collection_planning import (
        plan_alternate_reports,
    )
    from disaster_monitor.domain.collection import ClaimedCollectionWork
    from disaster_monitor.domain.news import NewsFeedItem

    provider = BingRssCollectionProvider()
    lead = NewsFeedItem(
        "lead",
        "Publisher",
        "Floods hit Lakeview",
        "https://publisher.example/report",
        None,
        None,
        NOW,
    )
    work = ClaimedCollectionWork(
        "work", "token", "retrieve", "publisher-articles", None, lead, 1
    )
    (alternate,) = plan_alternate_reports(work, (provider,), observed_at=NOW)
    assert alternate.provider == provider.source_id
    assert alternate.alternate_for == lead.canonical_url
    assert "flood" in alternate.query.casefold()
    assert not plan_alternate_reports(
        replace(work, alternate_depth=1), (provider,), observed_at=NOW
    )
    await provider.aclose()


async def test_index_summary_is_only_an_alternate_search_hint():
    from disaster_monitor.application.incidents.collection_planning import (
        plan_alternate_reports,
    )
    from disaster_monitor.domain.collection import ClaimedCollectionWork
    from disaster_monitor.domain.news import NewsFeedItem

    provider = BingRssCollectionProvider()
    lead = NewsFeedItem(
        "index-reference",
        "publisher.example",
        "Article title unavailable",
        "https://publisher.example/report",
        None,
        None,
        discovery_hint="Floods struck Lakeview. Nine people were reported dead.",
    )
    work = ClaimedCollectionWork(
        "work", "token", "retrieve", "publisher-articles", None, lead, 1
    )
    (alternate,) = plan_alternate_reports(work, (provider,), observed_at=NOW)
    assert "Lakeview" in alternate.query
    assert "flood" in alternate.query.casefold()
    assert "title unavailable" not in alternate.query
    await provider.aclose()


async def test_recent_feed_work_is_shared_across_windows_without_weekly_duplicates():
    provider = BingRssCollectionProvider()
    one = plan_collection(
        ReportingInterval.at_start(1, NOW), (provider,), observed_at=NOW
    )
    month = plan_collection(
        ReportingInterval.at_start(30, NOW), (provider,), observed_at=NOW
    )
    assert len(one) == len(month) == len(provider.queries)
    assert {p.key for p in one} == {p.key for p in month}
    assert (
        len(provider.queries) == 14
    )  # Broad and human-impact variants for seven hazards.
    await provider.aclose()


@pytest.mark.parametrize(
    "body",
    [
        b"not XML",
        b"<html><body>Error</body></html>",
        b'<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><rss>&y;</rss>',
    ],
)
async def test_invalid_or_unsafe_feed_is_a_failure_not_empty_success(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    ) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        with pytest.raises(CollectionProviderError, match="RSS"):
            await provider.fetch_page(
                CollectionPartition(
                    provider.source_id, "flood", NOW - timedelta(days=1), NOW
                )
            )


async def test_refusal_is_one_attempt_and_retains_provider_retry_after():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "1800"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        with pytest.raises(CollectionProviderError) as error:
            await provider.fetch_page(
                CollectionPartition(
                    provider.source_id, "flood", NOW - timedelta(days=1), NOW
                )
            )
    assert error.value.outcome == "rate_limited"
    assert error.value.retry_after_seconds == 1800
    assert len(calls) == 1
