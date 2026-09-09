from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.infrastructure.news.feeds import (
    GdeltDocNewsFeed,
    LicensedJsonNewsFeed,
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
async def test_licensed_gateway_sends_bearer_token_and_skips_invalid_items() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "ap-1",
                        "publisher": "Associated Press",
                        "title": "Major flood forces evacuations in Test Region",
                        "url": "https://apnews.com/article/test-flood",
                        "published_at": "2026-09-09T11:00:00Z",
                    },
                    {"id": "invalid"},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = LicensedJsonNewsFeed(
        source_id="ap-news",
        endpoint="https://licensed-gateway.example/ap",
        token="secret",
        client=client,
    )

    items = await feed.fetch_since(since=NOW - timedelta(hours=1), now=NOW)
    await client.aclose()

    assert [item.external_id for item in items] == ["ap-1"]


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
