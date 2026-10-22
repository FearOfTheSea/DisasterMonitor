"""Archive traversal is opt-in and honours the parent news switches."""

import httpx
import pytest
from conftest import FakeLanguageModel

from disaster_monitor.infrastructure.composition import (
    AppDependencyOverrides,
    build_app_dependencies,
)
from disaster_monitor.infrastructure.configuration import Settings


@pytest.mark.parametrize(
    "news,gdelt,archive,expected",
    [
        (True, True, True, True),
        (True, True, False, False),
        (True, False, True, False),
        (False, True, True, False),
    ],
)
async def test_composed_archive_source_honours_configuration(
    tmp_path, monkeypatch, news, gdelt, archive, expected
):
    requests = []

    def respond(request):
        requests.append(request.url)
        return httpx.Response(
            404 if request.url.host == "data.gdeltproject.org" else 429
        )

    async_client = httpx.AsyncClient

    def controlled_client(*args, **kwargs):
        return async_client(*args, **kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", controlled_client)
    settings = Settings(
        _env_file=None,
        news_sensing_enabled=news,
        gdelt_news_enabled=gdelt,
        gdelt_archive_enabled=archive,
        bing_news_rss_enabled=False,
        wikipedia_news_enabled=False,
        discovery_page_budget=1,
        discovery_pass_seconds=10,
        country_catalog_root=tmp_path / "countries",
        country_catalog_automatic_updates=False,
        discovery_collection_path=tmp_path / "journal.sqlite",
        discovery_scan_store_path=tmp_path / "scans",
        event_media_enabled=False,
    )
    dependencies = build_app_dependencies(
        settings, overrides=AppDependencyOverrides(model=FakeLanguageModel())
    )
    try:
        service = dependencies.discovery_scans
        assert service is not None
        scan = await service.start(1)
        await service.wait(scan.scan_id)
        assert any(url.host == "data.gdeltproject.org" for url in requests) is expected
    finally:
        await dependencies.lifecycle.shutdown()
