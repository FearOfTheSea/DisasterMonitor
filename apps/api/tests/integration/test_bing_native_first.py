"""A bounded first request must reach the configured native market."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from disaster_monitor.domain.collection import CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.news.bing_collection import (
    BingRssCollectionProvider,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 27, 20, tzinfo=UTC)
RSS = b"""<rss><channel><item><title>Flood report</title>
<link>https://daily.example/report</link>
<pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>"""


@pytest.mark.parametrize(
    "query,market",
    [
        ('"inundaciones" muertos', "es-MX"),
        ('"glissement de terrain" morts', "fr-FR"),
        ('"banjir" tewas', "id-ID"),
        ('"deslizamento" mortos', "pt-BR"),
        ('"Hochwasser" Tote', "de-DE"),
        ('"sel" öldü', "tr-TR"),
        ('"فيضانات" قتلى', "ar-SA"),
    ],
)
async def test_one_request_budget_reaches_native_market(tmp_path, query, market):
    store = SQLiteCollectionJournal(tmp_path / "collection.sqlite")
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(30, NOW))
    partition = CollectionPartition(
        "bing-rss-discovery", query, NOW - timedelta(hours=6), NOW
    )
    await store.attach(run, (partition,), now=NOW, budget=1)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        work = await store.claim("search", "reader", now=NOW)
        assert work is not None
        page = await provider.fetch_page(work.partition)
        assert await store.commit_page(work, page, now=NOW)
        assert await store.claim("search", "overbudget", now=NOW) is None
    assert len(calls) == 1
    assert calls[0].url.params["mkt"] == market
    assert page.next_cursor == "native-first-relevance"
    assert len(page.leads) == 1 and not page.articles
    await store.finish_pass(now=NOW)
    reopened = SQLiteCollectionJournal(tmp_path / "collection.sqlite")
    progress = (await reopened.snapshot(run.scan_id, now=NOW)).progress
    assert progress.pages_acquired == 1 and progress.searches_pending == 1


@pytest.mark.parametrize(
    "cursor,market,next_cursor",
    [
        ("relevance", "en-US", "native-recent"),
        ("native-recent", "id-ID", "native-relevance"),
        ("native-relevance", "id-ID", None),
    ],
)
async def test_existing_native_query_cursors_keep_their_original_meaning(
    cursor, market, next_cursor
):
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200, content=RSS)
        )
    ) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        partition = CollectionPartition(
            "bing-rss-discovery",
            '"banjir" tewas',
            NOW - timedelta(hours=6),
            NOW,
            cursor=cursor,
            generation="collection-v71:old",
        )
        page = await provider.fetch_page(partition)
    assert calls[0].url.params["mkt"] == market
    assert page.next_cursor == next_cursor
