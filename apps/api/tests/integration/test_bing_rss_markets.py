"""Native seed markets supplement bounded U.S. pages without guessing language."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from disaster_monitor.application.incidents.collection_planning import plan_collection
from disaster_monitor.domain.collection import (
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.news.bing_collection import (
    BingRssCollectionProvider,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
RSS = b"""<rss><channel><item><title>Regional flood reporting</title>
<link>https://daily.example/story</link>
<pubDate>Sat, 24 Oct 2026 09:00:00 GMT</pubDate>
<description>Two deaths reported.</description></item></channel></rss>"""


def partition(query, cursor=""):
    return CollectionPartition(
        "bing-rss-discovery", query, NOW - timedelta(hours=6), NOW, cursor=cursor
    )


@pytest.mark.parametrize(
    ("query", "native_market"),
    [
        ('"inundaciones" muertos', "es-MX"),
        ('"terremoto" fallecidos', "es-MX"),
        ('"glissement de terrain" morts', "fr-FR"),
        ('"cyclone" morts', "fr-FR"),
        ('"longsor" tewas', "id-ID"),
        ('"gempa" meninggal', "id-ID"),
        ('"deslizamento" mortos', "pt-BR"),
        ('"enxurrada" morreu', "pt-BR"),
    ],
)
async def test_native_seed_retains_both_us_orderings_before_native_orderings(
    query, native_market
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        cursor = ""
        pages = []
        for expected_cursor in ("relevance", "native-recent", "native-relevance", None):
            page = await provider.fetch_page(partition(query, cursor))
            assert page.next_cursor == expected_cursor
            assert len(page.leads) == 1
            assert page.leads[0].published_at is None
            assert not page.articles
            assert page.saturated
            pages.append(page)
            cursor = page.next_cursor
    assert all(
        any("market" in notice.casefold() for notice in page.notices) for page in pages
    )
    assert [r.url.params["mkt"] for r in calls] == [
        "en-US",
        "en-US",
        native_market,
        native_market,
    ]
    assert [r.url.params["qft"] for r in calls] == [
        'interval="9" sortbydate="1"',
        'interval="9"',
    ] * 2
    assert all(r.url.params["q"] == query for r in calls)


@pytest.mark.parametrize(
    "query",
    [
        '"flood" killed',
        '"cyclone"',
        "Actual native headline outside configured seeds",
        "Inundaciones dejaron muertos en una ciudad",
        "Longsor menewaskan warga di desa",
    ],
)
async def test_english_and_unrecognized_headline_queries_keep_two_us_pages(query):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        assert (await provider.fetch_page(partition(query))).next_cursor == "relevance"
        assert (
            await provider.fetch_page(partition(query, "relevance"))
        ).next_cursor is None
    assert len(calls) == 2
    assert all(r.url.params["mkt"] == "en-US" for r in calls)


@pytest.mark.parametrize("cursor", ["native-recent", "native-relevance"])
async def test_native_cursor_for_unconfigured_query_is_rejected_before_request(cursor):
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200, content=RSS)
        )
    ) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        with pytest.raises(CollectionProviderError, match="continuation"):
            await provider.fetch_page(partition('"flood" killed', cursor))
    assert not calls


async def test_native_pages_resume_across_restarts_with_one_request_budget(tmp_path):
    path = tmp_path / "collection.sqlite"
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(30, NOW))
    query = '"banjir" tewas'
    store = SQLiteCollectionJournal(path)
    await store.attach(run, (partition(query),), now=NOW, budget=1)
    calls = []

    def respond(request):
        calls.append(request)
        body = RSS.replace(b"/story", f"/story-{len(calls)}".encode())
        return httpx.Response(200, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        for cursor in ("", "relevance", "native-recent", "native-relevance"):
            work = await store.claim("search", "reader", now=NOW)
            assert work is not None and work.partition.cursor == cursor
            page = await provider.fetch_page(work.partition)
            assert await store.commit_page(work, page, now=NOW)
            assert await store.claim("search", "over-budget", now=NOW) is None
            await store.finish_pass(now=NOW)
            store = SQLiteCollectionJournal(path)
            progress = (await store.snapshot(run.scan_id, now=NOW)).progress
            assert progress.searches_pending == (0 if page.next_cursor is None else 1)
            if page.next_cursor is not None:
                await store.continue_scan(run.scan_id, now=NOW, budget=1)
    progress = (await store.snapshot(run.scan_id, now=NOW)).progress
    assert progress.pages_acquired == 4
    assert progress.leads_acquired == 4
    assert progress.searches_saturated == 1
    assert len(calls) == 4


@pytest.mark.parametrize(
    "query",
    [
        '"inundaciones" muertos',
        '"glissement de terrain" morts',
        '"longsor" tewas',
        '"deslizamento" mortos',
    ],
)
async def test_alternate_headline_does_not_expand_even_when_it_equals_a_seed(query):
    calls = []
    work = replace(partition(query), alternate_for="https://origin.example/article")

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        assert (await provider.fetch_page(work)).next_cursor == "relevance"
        assert (
            await provider.fetch_page(replace(work, cursor="relevance"))
        ).next_cursor is None
        with pytest.raises(CollectionProviderError, match="continuation"):
            await provider.fetch_page(replace(work, cursor="native-recent"))
    assert len(calls) == 2
    assert all(r.url.params["mkt"] == "en-US" for r in calls)


async def test_expanded_seed_traversal_resumes_with_the_original_shared_pass_budget(
    tmp_path,
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=b"<rss><channel/></rss>")

    store = SQLiteCollectionJournal(tmp_path / "collection.sqlite")
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(30, NOW))
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        partitions = plan_collection(run.interval, (provider,), observed_at=NOW)
        assert len(partitions) == 106
        await store.attach(run, partitions, now=NOW, budget=200)
        viewers = []
        for days in (1, 3, 7, 14):
            viewer = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(days, NOW))
            shared = plan_collection(viewer.interval, (provider,), observed_at=NOW)
            assert {p.key for p in shared} == {p.key for p in partitions}
            await store.attach(viewer, shared, now=NOW, budget=200)
            viewers.append(viewer)
        while work := await store.claim("search", "collector", now=NOW):
            page = await provider.fetch_page(work.partition)
            assert await store.commit_page(work, page, now=NOW)
        progress = (await store.snapshot(run.scan_id, now=NOW)).progress
        assert len(calls) == progress.pages_acquired == 200
        assert progress.searches_pending > 0
        assert progress.provider_requests == (("bing-rss-discovery", 200),)
        assert set(r.url.params["q"] for r in calls) == set(provider.queries)
        await store.finish_pass(now=NOW)
        store = SQLiteCollectionJournal(tmp_path / "collection.sqlite")
        await store.continue_scan(run.scan_id, now=NOW, budget=200)
        before = len(calls)
        while work := await store.claim("search", "collector", now=NOW):
            page = await provider.fetch_page(work.partition)
            assert await store.commit_page(work, page, now=NOW)
        assert len(calls) - before == 168
    progress = (await store.snapshot(run.scan_id, now=NOW)).progress
    assert len(calls) == progress.pages_acquired == 368
    assert progress.searches_pending == 0
    assert progress.searches_saturated == 106
    assert (
        progress.searches_completed == 0
    )  # Bounded RSS pages do not exhaust an index.
    assert progress.provider_requests == (("bing-rss-discovery", 368),)
    assert set(r.url.params["q"] for r in calls) == set(provider.queries)
    for viewer in viewers:
        shared = (await store.snapshot(viewer.scan_id, now=NOW)).progress
        assert shared.pages_acquired == 368
        assert shared.provider_requests == progress.provider_requests
