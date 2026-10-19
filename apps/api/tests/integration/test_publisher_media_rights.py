"""Publisher permission conditions apply before fetching and at every redirect."""

from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.media import MediaEventContext, MediaRightsStatus
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.media.news_scraper import NewsEventMediaProvider

PAGE = "https://www.directrelief.org/2026/10/flood-response/"
IMAGE = "https://i0.wp.com/www.directrelief.org/wp-content/uploads/2026/10/flood.jpg"


def context():
    now = datetime(2026, 10, 6, tzinfo=UTC)
    source = SourceReference(
        "fixture",
        "Direct Relief",
        "Flood response in Nepal",
        PAGE,
        now,
        None,
        now,
        "secondary",
    )
    return MediaEventContext(
        "event:1",
        "physical:1",
        Disaster.FLOOD,
        "Nepal",
        now,
        (),
        "NPL",
        ("Nepal",),
        None,
        None,
        collected_articles=(source,),
    )


def article(image=IMAGE, credit="(Photo by Jane Doe for Direct Relief)"):
    return f'''<head><meta property="og:title" content="Flood response in Nepal">
    <meta property="og:image" content="{image}"></head><article><figure>
    <img src="{image}"><figcaption>Flood response in Nepal. {credit}</figcaption>
    </figure></article>'''


@pytest.mark.asyncio
async def test_directrelief_requires_noncommercial_use_and_retains_credit_and_license():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, text=article(), headers={"content-type": "text/html"}
            )
        )
    ) as client:
        for enabled in (False, True):
            provider = NewsEventMediaProvider(
                timeout_seconds=2,
                maximum_page_bytes=100_000,
                maximum_image_bytes=100_000,
                client=client,
                noncommercial_use=enabled,
            )
            batch = await provider.discover(context(), now=context().event_time)
            if not enabled:
                assert not batch.candidates
                assert "noncommercial" in batch.unavailable_sources[0].detail
            else:
                assert len(batch.candidates) == 1
                photo = batch.candidates[0]
                assert photo.credit == "Jane Doe for Direct Relief"
                assert photo.caption.endswith("(Photo by Jane Doe for Direct Relief)")
                assert photo.rights_status is MediaRightsStatus.LICENSED_REUSE
                assert photo.license_name == "CC BY-NC-ND 4.0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image,credit",
    [
        (IMAGE, "(Photo by Unlicensed Agency)"),
        (
            "https://i0.wp.com/attacker.test/image.jpg",
            "(Photo by Jane Doe for Direct Relief)",
        ),
    ],
)
async def test_publisher_credit_or_proxy_namespace_cannot_be_bypassed(image, credit):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, text=article(image, credit), headers={"content-type": "text/html"}
            )
        )
    ) as client:
        provider = NewsEventMediaProvider(
            timeout_seconds=2,
            maximum_page_bytes=100_000,
            maximum_image_bytes=100_000,
            client=client,
            noncommercial_use=True,
        )
        batch = await provider.discover(context(), now=context().event_time)
    assert not batch.candidates
    assert batch.unavailable_sources


@pytest.mark.asyncio
async def test_asset_redirect_cannot_escape_publisher_namespace_on_shared_cdn():
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if str(request.url) == PAGE:
            return httpx.Response(
                200, text=article(), headers={"content-type": "text/html"}
            )
        return httpx.Response(
            302, headers={"location": "https://i0.wp.com/attacker.test/image.jpg"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = NewsEventMediaProvider(
            timeout_seconds=2,
            maximum_page_bytes=100_000,
            maximum_image_bytes=100_000,
            client=client,
            noncommercial_use=True,
        )
        batch = await provider.discover(context(), now=context().event_time)
        with pytest.raises(ValueError):
            await provider.retrieve(batch.candidates[0])
    assert requests == [PAGE, IMAGE]
