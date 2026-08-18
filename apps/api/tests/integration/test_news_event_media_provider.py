from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.media import MediaEventContext
from disaster_monitor.domain.disaster import Hazard
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
        hazard=Hazard.EARTHQUAKE,
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
        hazard=Hazard.EARTHQUAKE,
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
