from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.media import MediaDiscoveryBatch, MediaEventContext
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.media.news_scraper import NewsEventMediaProvider

NOW = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.mark.asyncio
async def test_collected_photos_preserve_dates_and_access_restrictions():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        assert request.url.host == "www.nbcnews.com"
        if request.url.path == "/broken":
            return httpx.Response(403)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="""
          <meta property="og:title" content="Riverton flood aftermath">
          <meta property="og:image" content="https://media-cldnry.s-nbcnews.com/flood.jpg">
          <article>
            <figure><img src="https://media-cldnry.s-nbcnews.com/flood.jpg">
<figcaption>Flood aftermath. A / AP</figcaption></figure>
            <figure><img src="https://media-cldnry.s-nbcnews.com/rescue.jpg">
<figcaption>Flood rescue. B / AP</figcaption></figure>
            <figure><img src="https://media-cldnry.s-nbcnews.com/logo.jpg">
<figcaption>Publisher logo</figcaption></figure>
            <aside>
<figure><img src="https://media-cldnry.s-nbcnews.com/other.jpg">
<figcaption>Related flood story</figcaption></figure></aside>
          </article>""",
        )

    sources = tuple(
        SourceReference("news", "Daily", "Riverton flood", url, None, None, NOW)
        for url in (
            "https://www.nbcnews.com/story",
            "https://unknown.example/story",
            "https://www.nbcnews.com/broken",
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NewsEventMediaProvider(
            timeout_seconds=1,
            maximum_page_bytes=20_000,
            maximum_image_bytes=20_000,
            client=client,
        )
        result = await provider.discover(
            MediaEventContext(
                "event",
                "event",
                Disaster.FLOOD,
                "Riverton",
                NOW,
                (),
                None,
                (),
                None,
                None,
                sources,
                False,
            ),
            now=NOW,
        )
    assert isinstance(result, MediaDiscoveryBatch)
    assert len(result.candidates) == 2
    assert all(
        c.published_at is None and c.captured_at is None for c in result.candidates
    )
    assert {s.source_page_url for s in result.unavailable_sources} == {
        s.canonical_url for s in sources[1:]
    }
    assert len(requested) == 2
    assert result.warnings
    assert any("HTTP 403" in s.detail for s in result.unavailable_sources)


async def test_challenge_response_is_not_a_successful_photo_collection():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                202,
                headers={"content-type": "text/html"},
                text='<meta property="og:image" content="https://media-cldnry.s-nbcnews.com/challenge.jpg">',
            )
        )
    ) as client:
        provider = NewsEventMediaProvider(
            timeout_seconds=1,
            maximum_page_bytes=20_000,
            maximum_image_bytes=20_000,
            client=client,
        )
        source = SourceReference(
            "news",
            "Daily",
            "Flood in Riverton",
            "https://www.nbcnews.com/report",
            NOW,
            None,
            NOW,
        )
        context = MediaEventContext(
            "event",
            "event",
            Disaster.FLOOD,
            "Riverton",
            NOW,
            (),
            None,
            (),
            None,
            None,
            (source,),
            True,
        )
        result = await provider.discover(context, now=NOW)
    assert not result.candidates
    assert "HTTP 202" in result.unavailable_sources[0].detail
