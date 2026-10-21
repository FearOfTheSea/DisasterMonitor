from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.media import (
    MediaContinuationError,
    MediaDiscoveryBatch,
    MediaEventContext,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.media.news_scraper import NewsEventMediaProvider

NOW = datetime(2026, 10, 18, tzinfo=UTC)


@pytest.mark.parametrize(
    "failure", ["changed_context", "changed_photos", "invalid_cursor"]
)
async def test_continuation_validates_its_original_source_collection(failure):
    changed = False
    requests = []

    def handler(request):
        requests.append(str(request.url))
        numbers = range(8) if not changed else reversed(range(8))
        figures = "".join(
            f'<figure><img src="https://media-cldnry.s-nbcnews.com/photo-{i}.jpg">'
            f"<figcaption>Flood aftermath scene {i}. A / AP</figcaption></figure>"
            for i in numbers
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=f"<article>{figures}</article>",
        )

    source = SourceReference(
        "news",
        "Daily",
        "Riverton flood",
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
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NewsEventMediaProvider(
            timeout_seconds=1,
            maximum_page_bytes=20000,
            maximum_image_bytes=20000,
            client=client,
        )
        first = await provider.discover(context, now=NOW, maximum_candidates=2)
        assert len(first.candidates) == 2 and first.next_cursor
        if failure == "changed_photos":
            changed = True
        if failure == "changed_context":
            context = replace(context, event_id="another-event")
        cursor = "malformed" if failure == "invalid_cursor" else first.next_cursor
        with pytest.raises(MediaContinuationError):
            await provider.discover(
                context, now=NOW, cursor=cursor, maximum_candidates=2
            )
        assert len(first.candidates) == 2
        assert len(requests) == (2 if failure == "changed_photos" else 1)


async def test_small_candidate_pages_do_not_discard_remaining_source_photographs():
    source = SourceReference(
        "news",
        "Daily",
        "Riverton flood",
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
    )
    figures = "".join(
        f'<figure><img src="https://media-cldnry.s-nbcnews.com/photo-{i}.jpg">'
        f"<figcaption>Flood aftermath scene {i}. A / AP</figcaption></figure>"
        for i in range(8)
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=f"<article>{figures}</article>",
            )
        )
    ) as client:
        provider = NewsEventMediaProvider(
            timeout_seconds=1,
            maximum_page_bytes=20000,
            maximum_image_bytes=20000,
            client=client,
        )
        cursor, seen = None, set()
        for _ in range(10):
            batch = await provider.discover(
                context, now=NOW, cursor=cursor, maximum_candidates=2
            )
            assert len(batch.candidates) <= 2
            seen.update(c.candidate_id for c in batch.candidates)
            cursor = batch.next_cursor
            if not cursor:
                break
        assert cursor is None and len(seen) == 8


async def test_photo_continuation_reaches_later_photos_and_articles_without_search():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        assert request.url.host == "www.nbcnews.com"
        article = int(request.url.path.removeprefix("/report-"))
        count = 8 if article == 0 else 1
        figures = "".join(
            f'<figure><img src="https://media-cldnry.s-nbcnews.com/scene-{article}-{i}.jpg">'
            f"<figcaption>Riverton flood aftermath scene {article}-{i}. "
            "A / AP</figcaption></figure>"
            for i in range(count)
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=f"<article>{figures}</article>",
        )

    sources = tuple(
        SourceReference(
            "news",
            "Daily",
            "Riverton flood",
            f"https://www.nbcnews.com/report-{i}",
            NOW,
            None,
            NOW,
        )
        for i in range(13)
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
        sources,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NewsEventMediaProvider(
            timeout_seconds=1,
            maximum_page_bytes=20000,
            maximum_image_bytes=20000,
            client=client,
        )
        first = await provider.discover(context, now=NOW)
        assert isinstance(first, MediaDiscoveryBatch)
        assert getattr(first, "next_cursor", None), (
            "Unprocessed source photographs need a continuation."
        )
        candidates = list(first.candidates)
        cursor = first.next_cursor
        for _ in range(25):
            if not cursor:
                break
            batch = await provider.discover(context, now=NOW, cursor=cursor)
            candidates.extend(batch.candidates)
            cursor = batch.next_cursor
        assert cursor is None
        assert len(candidates) == len({c.candidate_id for c in candidates}) == 20
        assert any(c.source_page_url.endswith("/report-12") for c in candidates)
        assert all("bing" not in url for url in requested)


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
