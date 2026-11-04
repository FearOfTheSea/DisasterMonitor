"""Google discovery is opt-in, news-gated, and shares a fixed metadata allowance."""

import sqlite3

import httpx
import pytest
from conftest import FakeLanguageModel
from pydantic import ValidationError

from disaster_monitor.infrastructure.composition import (
    AppDependencyOverrides,
    build_app_dependencies,
)
from disaster_monitor.infrastructure.configuration import Settings


@pytest.mark.parametrize(
    "news,google,legacy,limit,expected",
    [
        (True, True, False, 2, True),
        (True, False, False, 2, False),
        (False, True, False, 2, False),
        (True, True, True, 2, True),
        (True, True, True, 7, True),
    ],
)
async def test_google_discovery_honours_switches_and_shared_limit(
    tmp_path, monkeypatch, news, google, legacy, limit, expected
):
    requests = []
    google_clients = []

    def respond(request):
        requests.append(request.url)
        return httpx.Response(200, text="<rss><channel></channel></rss>")

    async_client = httpx.AsyncClient

    def controlled_client(*args, **kwargs):
        def observed(request):
            if request.url.host == "news.google.com":
                google_clients.append(client)
            return respond(request)

        client = async_client(*args, **kwargs, transport=httpx.MockTransport(observed))
        return client

    monkeypatch.setattr(httpx, "AsyncClient", controlled_client)
    settings = Settings(
        _env_file=None,
        news_sensing_enabled=news,
        google_news_rss_enabled=google,
        discovery_metadata_request_limit=limit,
        gdelt_news_enabled=legacy,
        gdelt_archive_enabled=legacy,
        gdelt_gkg_enabled=legacy,
        bing_news_rss_enabled=legacy,
        wikipedia_news_enabled=legacy,
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
        scan = await service.start(1)
        await service.wait(scan.scan_id)
        google_requests = sum(url.host == "news.google.com" for url in requests)
        assert google_requests <= int(expected)
        if not legacy or limit >= 7:
            assert google_requests == int(expected)
        with sqlite3.connect(settings.discovery_collection_path) as db:
            assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] <= limit
            providers = {
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT provider FROM work WHERE kind='search'"
                )
            }
            assert ("google-rss-discovery" in providers) == expected
            if legacy:
                # Two shared requests cannot guarantee a turn for every one of
                # seven providers. Unstarted roots remain durably planned.
                assert providers == {
                    "reliefweb-discovery",
                    "bing-rss-discovery",
                    "wikipedia-citation-discovery",
                    "gdelt-discovery",
                    "gdelt-archive-discovery",
                    "gdelt-gkg-discovery",
                    "google-rss-discovery",
                }
    finally:
        await dependencies.lifecycle.shutdown()
    assert all(client.is_closed for client in google_clients)


def test_google_defaults_off_and_metadata_limit_is_bounded():
    settings = Settings(_env_file=None)
    assert not settings.google_news_rss_enabled
    assert settings.discovery_metadata_request_limit is None
    for invalid in (0, 1201):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, discovery_metadata_request_limit=invalid)
