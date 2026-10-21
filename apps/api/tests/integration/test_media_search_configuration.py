"""The RSS setting applies to every news search without blocking retained articles."""

from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.media import MediaDiscoveryBatch, MediaEventContext
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.composition_builders import (
    build_event_media_services,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.media.news_scraper import NewsEventMediaProvider

NOW = datetime(2026, 10, 21, tzinfo=UTC)
CONTEXT = MediaEventContext(
    "event:fixture",
    "physical:fixture",
    Disaster.FLOOD,
    "Riverton",
    NOW,
    (),
    None,
    (),
    None,
    None,
)


async def test_media_provider_does_not_search_rss_by_default():
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, text="<rss><channel/></rss>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = NewsEventMediaProvider(
            timeout_seconds=1,
            maximum_page_bytes=10000,
            maximum_image_bytes=10000,
            client=client,
        )
        result = await provider.discover(CONTEXT, now=NOW)

    assert requests == []
    assert isinstance(result, MediaDiscoveryBatch)
    assert result.candidates == () and result.next_cursor is None
    assert any("search is disabled" in warning for warning in result.warnings)


@pytest.mark.parametrize("enabled", [False, True])
async def test_composed_media_search_honours_shared_rss_setting(
    tmp_path, monkeypatch, enabled
):
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, text="<rss><channel/></rss>")

    async_client = httpx.AsyncClient

    def controlled_client(*args, **kwargs):
        return async_client(*args, **kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", controlled_client)
    services = build_event_media_services(
        Settings(
            bing_news_rss_enabled=enabled,
            event_media_enabled=True,
            event_media_blob_root=tmp_path / "media",
        ),
        clock=lambda: NOW,
    )
    assert services.discovery is not None
    try:
        gallery = await services.discovery.discover(CONTEXT)
        assert gallery is not None
        assert not gallery.items
        assert bool(requests) is enabled
        assert any("search is disabled" in w for w in gallery.warnings) is not enabled
        assert all(httpx.URL(url).host == "www.bing.com" for url in requests)
    finally:
        await services.discovery.aclose()
