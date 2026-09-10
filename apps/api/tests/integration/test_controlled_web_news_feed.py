from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.domain.web_collection import (
    ApprovedWebSource,
    WebAcquisitionMode,
    WebFetchOutcome,
)
from disaster_monitor.infrastructure.news.controlled_web import (
    BoundedWebFetcher,
    ControlledWebNewsFeed,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

NOW = datetime(2026, 9, 10, 8, tzinfo=UTC)
RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Disasters</title><item>
<guid>fire-1</guid><title>Major wildfire forces evacuations in Test Region</title>
<link>https://news.example/articles/fire-1</link>
<pubDate>Thu, 10 Sep 2026 07:30:00 GMT</pubDate>
</item></channel></rss>"""


def _source(**overrides: object) -> ApprovedWebSource:
    values = {
        "source_id": "approved-test-news",
        "publisher_name": "news.example",
        "feed_url": "https://news.example/disasters.xml",
        "allowed_hosts": ("news.example",),
        "allowed_path_prefixes": ("/disasters", "/articles/"),
        "acquisition_mode": WebAcquisitionMode.RSS_ATOM,
        "user_agent": "DisasterMonitor/1.0 (+mailto:ops@example.org)",
        "contact_email": "ops@example.org",
        "robots_policy_url": "https://news.example/robots.txt",
        "terms_url": "https://news.example/terms",
        "reviewed_at": NOW - timedelta(days=1),
        "review_expires_at": NOW + timedelta(days=30),
        "crawl_delay_seconds": 60,
        "request_limit_per_run": 1,
        "maximum_response_bytes": 100_000,
    }
    values.update(overrides)
    return ApprovedWebSource(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_feed_collects_metadata_and_uses_conditional_requests() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("if-none-match") == '"feed-v1"':
            return httpx.Response(304)
        return httpx.Response(
            200,
            content=RSS,
            headers={"content-type": "application/rss+xml", "etag": '"feed-v1"'},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = InMemoryOperationalRepository()
    feed = ControlledWebNewsFeed(
        _source(crawl_delay_seconds=0),
        BoundedWebFetcher(client=client, resolver=lambda host: ("93.184.216.34",)),
        store,
    )

    first = await feed.fetch_since(since=NOW - timedelta(hours=1), now=NOW)
    second = await feed.fetch_since(
        since=NOW - timedelta(hours=1), now=NOW + timedelta(minutes=1)
    )
    await client.aclose()

    assert [item.external_id for item in first] == ["fire-1"]
    assert first[0].publisher == "news.example"
    assert second == ()
    assert requests[0].headers["user-agent"].startswith("DisasterMonitor/")
    assert requests[1].headers["if-none-match"] == '"feed-v1"'
    assert [
        audit.outcome
        for audit in reversed(
            await store.web_fetch_audits(source_id="approved-test-news")
        )
    ] == [
        WebFetchOutcome.SUCCESS,
        WebFetchOutcome.NOT_MODIFIED,
    ]


@pytest.mark.asyncio
async def test_fetcher_rejects_private_destinations_before_request() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, content=RSS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = ControlledWebNewsFeed(
        _source(),
        BoundedWebFetcher(client=client, resolver=lambda host: ("127.0.0.1",)),
        InMemoryOperationalRepository(),
    )

    with pytest.raises(ValueError, match="public destination"):
        await feed.fetch_since(since=NOW - timedelta(hours=1), now=NOW)

    await client.aclose()
    assert request_count == 0


@pytest.mark.asyncio
async def test_feed_rejects_redirects_outside_the_admitted_boundary() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                302, headers={"location": "https://other.example/feed.xml"}
            )
        )
    )
    feed = ControlledWebNewsFeed(
        _source(),
        BoundedWebFetcher(client=client, resolver=lambda host: ("93.184.216.34",)),
        InMemoryOperationalRepository(),
    )

    with pytest.raises(ValueError, match="admitted URL"):
        await feed.fetch_since(since=NOW - timedelta(hours=1), now=NOW)

    await client.aclose()


@pytest.mark.asyncio
async def test_redirects_cannot_exceed_the_per_run_request_budget() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            302, headers={"location": "https://news.example/disasters-v2.xml"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = ControlledWebNewsFeed(
        _source(request_limit_per_run=1),
        BoundedWebFetcher(client=client, resolver=lambda host: ("93.184.216.34",)),
        InMemoryOperationalRepository(),
    )

    with pytest.raises(ValueError, match="request budget"):
        await feed.fetch_since(since=NOW - timedelta(hours=1), now=NOW)

    await client.aclose()
    assert requests == 1


@pytest.mark.asyncio
async def test_feed_fails_closed_for_expired_review_and_hostile_xml() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b'<!DOCTYPE rss [<!ENTITY x "boom">]><rss>&x;</rss>',
                headers={"content-type": "application/rss+xml"},
            )
        )
    )

    def resolver(host: str) -> tuple[str, ...]:
        return ("93.184.216.34",)

    expired = ControlledWebNewsFeed(
        _source(review_expires_at=NOW),
        BoundedWebFetcher(client=client, resolver=resolver),
        InMemoryOperationalRepository(),
    )
    with pytest.raises(ValueError, match="not currently admitted"):
        await expired.fetch_since(since=NOW - timedelta(hours=1), now=NOW)

    hostile = ControlledWebNewsFeed(
        _source(),
        BoundedWebFetcher(client=client, resolver=resolver),
        InMemoryOperationalRepository(),
    )
    with pytest.raises(ValueError, match="unsafe XML"):
        await hostile.fetch_since(since=NOW - timedelta(hours=1), now=NOW)

    await client.aclose()


@pytest.mark.asyncio
async def test_repeated_failures_open_a_source_specific_circuit() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(503, headers={"content-type": "application/rss+xml"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = InMemoryOperationalRepository()
    feed = ControlledWebNewsFeed(
        _source(crawl_delay_seconds=0),
        BoundedWebFetcher(client=client, resolver=lambda host: ("93.184.216.34",)),
        store,
    )

    for minute in range(3):
        with pytest.raises(ValueError, match="unsuccessful response"):
            await feed.fetch_since(
                since=NOW - timedelta(hours=1), now=NOW + timedelta(minutes=minute)
            )
    with pytest.raises(ValueError, match="circuit is open"):
        await feed.fetch_since(
            since=NOW - timedelta(hours=1), now=NOW + timedelta(minutes=3)
        )

    await client.aclose()
    assert requests == 3
    state = await store.read_web_fetch_state("approved-test-news")
    assert state is not None
    assert state.circuit_open_until == NOW + timedelta(minutes=32)


@pytest.mark.asyncio
async def test_news_sitemap_extracts_only_admitted_timestamped_metadata() -> None:
    sitemap = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
      xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
      <url><loc>https://news.example/articles/flood-1</loc><news:news>
        <news:publication_date>2026-09-10T07:45:00Z</news:publication_date>
        <news:title>Major flood forces evacuations in Test Region</news:title>
      </news:news></url>
      <url><loc>https://other.example/articles/rejected</loc><news:news>
        <news:publication_date>2026-09-10T07:50:00Z</news:publication_date>
        <news:title>Major flood outside the boundary</news:title>
      </news:news></url>
    </urlset>"""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=sitemap,
                headers={"content-type": "application/xml"},
            )
        )
    )
    feed = ControlledWebNewsFeed(
        _source(acquisition_mode=WebAcquisitionMode.NEWS_SITEMAP),
        BoundedWebFetcher(client=client, resolver=lambda host: ("93.184.216.34",)),
        InMemoryOperationalRepository(),
    )

    items = await feed.fetch_since(since=NOW - timedelta(hours=1), now=NOW)

    await client.aclose()
    assert [item.canonical_url for item in items] == [
        "https://news.example/articles/flood-1"
    ]
