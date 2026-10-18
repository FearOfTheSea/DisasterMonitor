import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.domain.discovery import ReportingInterval
from disaster_monitor.infrastructure.news.discovery_feed import GdeltDiscoveryFeed
from disaster_monitor.infrastructure.news.reliefweb_discovery import (
    ReliefWebDiscoveryFeed,
)
from disaster_monitor.infrastructure.news.request_schedule import ScheduledNewsJson

NOW = datetime(2026, 10, 18, tzinfo=UTC)


async def test_empty_report_body_is_not_presented_as_successful_text_extraction():
    def respond(request):
        return httpx.Response(
            200,
            json={
                "totalCount": 1,
                "data": [
                    {
                        "fields": {
                            "title": "Flood situation report",
                            "url": "https://reliefweb.int/node/123",
                            "date": {"original": "2026-10-17T00:00:00Z"},
                            "body": "",
                        }
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = ReliefWebDiscoveryFeed(
            app_name="configured-test", client=client, minimum_request_interval=0
        )
        batches = [
            batch
            async for batch in feed.discover(
                interval=ReportingInterval.at_start(7, NOW)
            )
        ]
    article = batches[0].articles[0]
    assert not article.text
    assert "no report text" in article.access_issue.lower()
    assert "midnight" in article.access_issue.lower()


async def test_overlapping_scans_share_article_reads_with_bounded_freshness():
    now = [0.0]

    class Reader:
        calls = 0

        async def read(self, url):
            self.calls += 1
            await asyncio.sleep(0)
            return (
                '<meta property="article:published_time" '
                'content="2026-10-17T10:00:00Z">'
                "<article><p>Two people died in the flood.</p></article>"
            )

    def respond(request):
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://publisher.example/flood",
                        "title": "Flood report",
                        "domain": "publisher.example",
                        "seendate": "20261017T100000Z",
                    }
                ]
            },
        )

    reader = Reader()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = GdeltDiscoveryFeed(
            client=client,
            reader=reader,
            maximum_queries=1,
            minimum_request_interval=0,
            clock=lambda: now[0],
        )

        async def collect(days):
            return [
                batch
                async for batch in feed.discover(
                    interval=ReportingInterval.at_start(days, NOW)
                )
            ]

        first, second = await asyncio.gather(collect(7), collect(30))
        assert reader.calls == 1
        assert (
            first[0].articles[0].source.retrieved_at
            == second[0].articles[0].source.retrieved_at
        )
        now[0] = 301
        await collect(7)
        assert reader.calls == 2


async def test_transient_query_timeout_retries_once_then_collects_other_categories():
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(408)
        return httpx.Response(200, json={"totalCount": 0, "data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = ReliefWebDiscoveryFeed(
            app_name="configured-test", client=client, minimum_request_interval=0
        )
        batches = [
            batch
            async for batch in feed.discover(
                interval=ReportingInterval.at_start(30, NOW)
            )
        ]
    assert len(calls) == 8
    assert sum(batch.successful_operations for batch in batches) == 7


async def test_reliefweb_date_ranges_use_supported_seconds_and_cover_fixed_interval():
    interval = ReportingInterval.at_start(30, NOW.replace(microsecond=123456))

    def respond(request):
        params = request.url.params
        start = params["filter[conditions][1][value][from]"]
        end = params["filter[conditions][1][value][to]"]
        assert "." not in start and "." not in end
        assert datetime.fromisoformat(start) <= interval.start
        assert datetime.fromisoformat(end) >= interval.end
        return httpx.Response(200, json={"totalCount": 0, "data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = ReliefWebDiscoveryFeed(
            app_name="configured-test", client=client, minimum_request_interval=0
        )
        batches = [batch async for batch in feed.discover(interval=interval)]
    assert sum(batch.successful_operations for batch in batches) == 7


async def test_scheduled_requests_share_work_and_expire_without_rewriting_metadata():
    calls = []
    time = [0.0]

    async def respond(request):
        calls.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, json={"articles": [], "retrieval": len(calls)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        schedule = ScheduledNewsJson(client, minimum_interval=0, clock=lambda: time[0])
        results = await asyncio.gather(
            *(
                schedule.get("https://provider.example/news", {"query": "flood"})
                for _ in range(10)
            )
        )
        assert len(calls) == 1
        assert all(result == results[0] for result in results)
        reused = await schedule.get("https://provider.example/news", {"query": "flood"})
        assert reused.payload["retrieval"] == 1
        assert reused.retrieved_at == results[0].retrieved_at
        assert reused.cached
        time[0] += 301
        assert (
            await schedule.get("https://provider.example/news", {"query": "flood"})
        ).payload["retrieval"] == 2


async def test_throttle_stops_gdelt_partitions_and_preserves_retry_reason():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "7200"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = GdeltDiscoveryFeed(client=client, minimum_request_interval=0)
        batches = [
            batch
            async for batch in feed.discover(
                interval=ReportingInterval.at_start(30, NOW)
            )
        ]
    assert len(calls) == 1
    assert sum(batch.failed_operations for batch in batches) >= 1
    assert any(
        "429" in issue and "7200" in issue
        for batch in batches
        for issue in batch.issues
    )
    assert any("unattempted" in issue for batch in batches for issue in batch.issues)


async def test_reliefweb_uses_original_publication_and_retains_partial_acquisition():
    queries = []

    def respond(request):
        query = request.url.params
        queries.append(query)
        if len(queries) == 2:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "totalCount": 2,
                "data": [
                    {
                        "id": "r1",
                        "fields": {
                            "title": "Flood in Delta: situation report",
                            "url": "https://reliefweb.int/report/example/flood-delta",
                            "body": (
                                "Officials reported two people killed by the flood."
                            ),
                            "date": {
                                "original": "2026-10-16T12:00:00Z",
                                "created": "2026-10-17T10:00:00Z",
                                "changed": "2026-10-17T11:00:00Z",
                            },
                            "source": [{"name": "Independent humanitarian reporter"}],
                            "primary_country": {"name": "Example country"},
                            "disaster": [{"id": "event1", "name": "Delta floods"}],
                        },
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = ReliefWebDiscoveryFeed(
            app_name="configured-test",
            client=client,
            maximum_records=1,
            maximum_pages=1,
            minimum_request_interval=0,
        )
        batches = [
            batch
            async for batch in feed.discover(
                interval=ReportingInterval.at_start(30, NOW)
            )
        ]
    article = next(article for batch in batches for article in batch.articles)
    assert article.source.published_at == NOW - timedelta(days=1, hours=12)
    assert article.indexed_at == NOW - timedelta(hours=14)
    assert article.source.updated_at == NOW - timedelta(hours=13)
    assert article.event_time is None
    assert article.geometry is None
    assert article.source.publisher == "Independent humanitarian reporter"
    assert article.text == "Officials reported two people killed by the flood."
    assert queries[0]["filter[conditions][1][field]"] == "date.original"
    assert any(batch.truncated for batch in batches)
    assert any(batch.failed_operations for batch in batches)


@pytest.mark.parametrize("app_name", [None, "", "change-me", "disaster-monitor-local"])
async def test_reliefweb_missing_access_is_explicit_and_does_not_request(app_name):
    def respond(request):
        pytest.fail("Unconfigured ReliefWeb must not make requests")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = ReliefWebDiscoveryFeed(app_name=app_name, client=client)
        batches = [
            batch
            async for batch in feed.discover(
                interval=ReportingInterval.at_start(7, NOW)
            )
        ]
    assert sum(batch.failed_operations for batch in batches) == 1
    assert "appname" in batches[0].issues[0]
