from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.domain.errors import DisasterInformationRuntimeError
from disaster_monitor.infrastructure.current_information import (
    google_news_rss_adapter,
)

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Newer report</title>
      <link>https://example.test/newer</link>
      <pubDate>Wed, 05 Aug 2026 06:30:00 GMT</pubDate>
      <description>&lt;b&gt;Preliminary&lt;/b&gt; damage update.</description>
      <source url="https://example.test">NHK</source>
    </item>
    <item>
      <title>Older report</title>
      <link>https://example.test/older</link>
      <pubDate>Tue, 04 Aug 2026 10:00:00 GMT</pubDate>
      <description>Assessment continues.</description>
      <source url="https://example.test">Reuters</source>
    </item>
    <item>
      <title>Newer report</title>
      <link>https://example.test/duplicate</link>
      <pubDate>Wed, 05 Aug 2026 06:20:00 GMT</pubDate>
      <description>Duplicate.</description>
      <source url="https://example.test">NHK</source>
    </item>
  </channel>
</rss>"""


@pytest.mark.asyncio
async def test_adapter_fetches_parses_sorts_and_deduplicates_reports() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, content=RSS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = google_news_rss_adapter.GoogleNewsRssDisasterInformationAdapter(
            base_url="https://news.test/rss/search",
            max_items=8,
            lookback_days=30,
            client=client,
            clock=lambda: datetime(2026, 8, 5, 7, 0, tzinfo=UTC),
        )
        result = await adapter.search("Japan earthquake latest damage")

    assert seen_request is not None
    assert seen_request.url.params["q"] == (
        "Japan earthquake latest damage when:30d"
    )
    assert result.retrieved_at == datetime(2026, 8, 5, 7, 0, tzinfo=UTC)
    assert [item.title for item in result.items] == ["Newer report", "Older report"]
    assert result.items[0].summary == "Preliminary damage update."
    assert result.items[0].source == "NHK"


@pytest.mark.asyncio
async def test_adapter_translates_http_and_xml_failures() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, content=b"bad gateway")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = google_news_rss_adapter.GoogleNewsRssDisasterInformationAdapter(
            client=client
        )
        with pytest.raises(DisasterInformationRuntimeError):
            await adapter.search("Japan earthquake")
