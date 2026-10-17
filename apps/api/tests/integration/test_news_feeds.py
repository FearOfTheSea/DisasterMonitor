from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.infrastructure.disaster.errors import DisasterProviderError
from disaster_monitor.infrastructure.news.feeds import (
    GdeltDocNewsFeed,
)

NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_gdelt_feed_preserves_publisher_and_publication_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["mode"] == "artlist"
        assert request.url.params["startdatetime"] == "20260909113000"
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://www.reuters.com/world/test-fire",
                        "title": "Major wildfire forces evacuations near Test Region",
                        "seendate": "20260909T114500Z",
                        "domain": "reuters.com",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = GdeltDocNewsFeed(client=client)

    items = await feed.fetch_since(since=NOW - timedelta(minutes=30), now=NOW)
    await client.aclose()

    assert len(items) == 1
    assert items[0].publisher == "reuters.com"
    assert items[0].published_at == datetime(2026, 9, 9, 11, 45, tzinfo=UTC)


@pytest.mark.asyncio
async def test_news_feed_rejects_oversized_responses() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b'{"articles": []}')
        )
    )
    feed = GdeltDocNewsFeed(client=client, maximum_response_bytes=4)

    with pytest.raises(ValueError, match="response exceeded"):
        await feed.fetch_since(since=NOW - timedelta(minutes=30), now=NOW)

    await client.aclose()


async def test_gdelt_retry_after_defers_followup_network_requests():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = GdeltDocNewsFeed(client=client)
        for _ in range(2):
            with pytest.raises((httpx.HTTPStatusError, DisasterProviderError)):
                await feed.fetch_since(since=NOW - timedelta(minutes=30), now=NOW)
        assert len(calls) == 1
