from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.media import MediaEventContext
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.media.news_scraper import NewsEventMediaProvider

NOW = datetime(2026, 8, 15, 12, tzinfo=UTC)
PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    + (640).to_bytes(4, "big")
    + (360).to_bytes(4, "big")
    + b"\x08\x06\x00\x00\x00"
)


@pytest.mark.asyncio
async def test_news_provider_extracts_registered_source_metadata_and_image() -> None:
    rss = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:News="urn:news"><channel><item>
<title>Rescuers search Colombia earthquake rubble</title>
<link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fwww.nbcnews.com%2Ffixture</link>
<description>Response to the Colombia earthquake.</description>
<pubDate>Mon, 10 Aug 2026 06:32:00 GMT</pubDate>
<News:Source>NBC News</News:Source>
</item></channel></rss>"""
    article = b"""<html><head>
<meta property="og:title" content="Rescuers search Colombia earthquake rubble">
<meta property="og:description" content="Emergency response in Colombia">
<meta property="og:image" content="https://media-cldnry.s-nbcnews.com/quake.jpg">
<meta property="article:published_time" content="2026-08-10T06:32:00Z">
</head><body><figure><img src="https://media-cldnry.s-nbcnews.com/quake.jpg">
<figcaption>Rescue workers in Colombia after the earthquake. Jane Doe / AP</figcaption>
</figure></body></html>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.bing.com":
            return httpx.Response(
                200, content=rss, headers={"content-type": "text/xml"}
            )
        if request.url.host == "www.nbcnews.com":
            return httpx.Response(
                200, content=article, headers={"content-type": "text/html"}
            )
        if request.url.host == "media-cldnry.s-nbcnews.com":
            return httpx.Response(
                200, content=PNG, headers={"content-type": "image/png"}
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = NewsEventMediaProvider(
        timeout_seconds=2,
        maximum_page_bytes=100_000,
        maximum_image_bytes=100_000,
        client=client,
    )
    context = MediaEventContext(
        event_id="us6000tjl2",
        physical_event_id="physical-event:fixture",
        disaster=Disaster.EARTHQUAKE,
        location="San José del Palmar, Colombia",
        event_time=datetime(2026, 8, 10, 5, 54, tzinfo=UTC),
        provider_ids=("us6000tjl2",),
        country_code="COL",
        country_terms=("Colombia",),
        latitude=4.95,
        longitude=-76.25,
    )

    candidates = await provider.discover(context, now=NOW)
    retrieved = await provider.retrieve(candidates[0])
    await client.aclose()

    assert len(candidates) == 1
    assert candidates[0].source_id == "event-media-nbc-news"
    assert candidates[0].caption.startswith("Rescue workers in Colombia")
    assert candidates[0].credit == "Jane Doe / AP"
    assert retrieved.media_type == "image/png"
    assert (retrieved.width, retrieved.height) == (640, 360)


@pytest.mark.asyncio
async def test_news_provider_refuses_an_image_outside_registered_hosts() -> None:
    rss = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><item>
<title>Rescuers search Colombia earthquake rubble</title>
<link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fwww.nbcnews.com%2Ffixture</link>
<description>Response to the Colombia earthquake.</description>
<pubDate>Mon, 10 Aug 2026 06:32:00 GMT</pubDate>
</item></channel></rss>"""
    article = b"""<html><head>
<meta property="og:title" content="Rescuers search Colombia earthquake rubble">
<meta property="og:image" content="https://unregistered.example/older-disaster.jpg">
</head></html>"""
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if request.url.host == "www.bing.com":
            return httpx.Response(
                200, content=rss, headers={"content-type": "text/xml"}
            )
        if request.url.host == "www.nbcnews.com":
            return httpx.Response(
                200, content=article, headers={"content-type": "text/html"}
            )
        raise AssertionError("The provider requested an unregistered media host.")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = NewsEventMediaProvider(
        timeout_seconds=2,
        maximum_page_bytes=100_000,
        maximum_image_bytes=100_000,
        client=client,
    )
    context = MediaEventContext(
        event_id="us6000tjl2",
        physical_event_id="physical-event:fixture",
        disaster=Disaster.EARTHQUAKE,
        location="San Jose del Palmar, Colombia",
        event_time=datetime(2026, 8, 10, 5, 54, tzinfo=UTC),
        provider_ids=("us6000tjl2",),
        country_code="COL",
        country_terms=("Colombia",),
        latitude=4.95,
        longitude=-76.25,
    )

    candidates = await provider.discover(context, now=NOW)
    await client.aclose()

    assert candidates == ()
    assert "unregistered.example" not in requested_hosts


@pytest.mark.asyncio
async def test_news_provider_backfills_pages_that_cannot_yield_candidates() -> None:
    def feed_item(index: int) -> str:
        return f"""<item>
<title>Colombia earthquake response {index}</title>
<link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fwww.nbcnews.com%2Ffixture-{index}</link>
<description>Response to the Colombia earthquake.</description>
<pubDate>Mon, 10 Aug 2026 06:{index:02d}:00 GMT</pubDate>
</item>"""

    rss = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss version="2.0"><channel>'
        + "".join(feed_item(index) for index in range(1, 6))
        + "</channel></rss>"
    ).encode()
    unusable_article = b"""<html><head>
<meta property="og:title" content="Colombia earthquake response">
</head></html>"""

    def usable_article(index: int) -> bytes:
        return f"""<html><head>
<meta property="og:title" content="Colombia earthquake response {index}">
<meta property="og:image" content="https://media-cldnry.s-nbcnews.com/quake-{index}.jpg">
</head></html>""".encode()

    requested_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.bing.com":
            return httpx.Response(
                200, content=rss, headers={"content-type": "text/xml"}
            )
        if request.url.host == "www.nbcnews.com":
            requested_pages.append(request.url.path)
            index = int(request.url.path.rsplit("-", 1)[-1])
            article = unusable_article if index >= 3 else usable_article(index)
            return httpx.Response(
                200, content=article, headers={"content-type": "text/html"}
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = NewsEventMediaProvider(
        timeout_seconds=2,
        maximum_page_bytes=100_000,
        maximum_image_bytes=100_000,
        candidate_limit=3,
        client=client,
    )
    context = MediaEventContext(
        event_id="us6000tjl2",
        physical_event_id="physical-event:fixture",
        disaster=Disaster.EARTHQUAKE,
        location="San Jose del Palmar, Colombia",
        event_time=datetime(2026, 8, 10, 5, 54, tzinfo=UTC),
        provider_ids=("us6000tjl2",),
        country_code="COL",
        country_terms=("Colombia",),
        latitude=4.95,
        longitude=-76.25,
    )

    candidates = await provider.discover(context, now=NOW)
    await client.aclose()

    assert [candidate.image_url for candidate in candidates] == [
        "https://media-cldnry.s-nbcnews.com/quake-2.jpg",
        "https://media-cldnry.s-nbcnews.com/quake-1.jpg",
    ]
    assert set(requested_pages) == {
        "/fixture-1",
        "/fixture-2",
        "/fixture-3",
        "/fixture-4",
        "/fixture-5",
    }


@pytest.mark.asyncio
async def test_news_provider_retries_transient_discovery_failures_once() -> None:
    rss = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><item>
<title>Colombia earthquake response</title>
<link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fwww.nbcnews.com%2Ffixture</link>
<description>Response to the Colombia earthquake.</description>
<pubDate>Mon, 10 Aug 2026 06:32:00 GMT</pubDate>
</item></channel></rss>"""
    article = b"""<html><head>
<meta property="og:title" content="Colombia earthquake response">
<meta property="og:image" content="https://media-cldnry.s-nbcnews.com/quake.jpg">
</head></html>"""
    search_attempts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.bing.com":
            query = str(request.url.params["q"])
            search_attempts[query] = search_attempts.get(query, 0) + 1
            if search_attempts[query] == 1:
                return httpx.Response(503)
            return httpx.Response(
                200, content=rss, headers={"content-type": "text/xml"}
            )
        if request.url.host == "www.nbcnews.com":
            return httpx.Response(
                200, content=article, headers={"content-type": "text/html"}
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = NewsEventMediaProvider(
        timeout_seconds=2,
        maximum_page_bytes=100_000,
        maximum_image_bytes=100_000,
        client=client,
    )
    context = MediaEventContext(
        event_id="us6000tjl2",
        physical_event_id="physical-event:fixture",
        disaster=Disaster.EARTHQUAKE,
        location="San Jose del Palmar, Colombia",
        event_time=datetime(2026, 8, 10, 5, 54, tzinfo=UTC),
        provider_ids=("us6000tjl2",),
        country_code="COL",
        country_terms=("Colombia",),
        latitude=4.95,
        longitude=-76.25,
    )

    candidates = await provider.discover(context, now=NOW)
    await client.aclose()

    assert len(candidates) == 1
    assert all(attempts == 2 for attempts in search_attempts.values())
