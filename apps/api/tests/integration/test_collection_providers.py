"""Provider protocols return one resumable page without publisher retrieval."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.domain.collection import (
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.infrastructure.news.collection_providers import (
    GdeltCollectionProvider,
    ReliefWebCollectionProvider,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


async def test_saturated_gdelt_page_saves_leads_and_split_children():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://publisher.example/flood",
                        "title": "Flood in Riverton",
                        "domain": "publisher.example",
                        "seendate": "20261018T120000Z",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GdeltCollectionProvider(client=client, limit=1, minimum_interval=0)
        part = CollectionPartition(
            provider.source_id, "flood", NOW - timedelta(days=1), NOW
        )
        page = await provider.fetch_page(part)
    assert len(requests) == 1
    assert len(page.leads) == 1
    assert not page.articles
    assert page.leads[0].published_at is None
    assert len(page.children) == 2
    assert page.children[0].end == page.children[1].start
    assert page.children[0].start == part.start
    assert page.children[1].end == part.end
    assert not page.saturated


async def test_irreducible_saturation_is_distinct_from_empty_success():
    def respond(request):
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://publisher.example/a",
                        "title": "Flood",
                        "seendate": "20261018T120000Z",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GdeltCollectionProvider(client=client, limit=1, minimum_interval=0)
        part = CollectionPartition(
            provider.source_id, "flood", NOW - timedelta(minutes=5), NOW
        )
        assert (await provider.fetch_page(part)).saturated


async def test_reliefweb_continuation_has_no_permanent_two_page_ceiling():
    offsets = []

    def respond(request):
        offsets.append(request.url.params["offset"])
        return httpx.Response(200, json={"totalCount": 61, "data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = ReliefWebCollectionProvider(
            app_name="approved-test", client=client, minimum_interval=0
        )
        part = CollectionPartition(
            provider.source_id, "Flood", NOW - timedelta(days=7), NOW
        )
        page = await provider.fetch_page(replace(part, cursor="40"))
    assert offsets == ["40"]
    assert page.next_cursor == "60"


@pytest.mark.parametrize(
    "status,outcome",
    [(429, "rate_limited"), (403, "access_refused"), (503, "transport_failed")],
)
async def test_provider_outcomes_preserve_retry_after_and_do_not_retry_internally(
    status, outcome
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "1800"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GdeltCollectionProvider(client=client, minimum_interval=0)
        part = CollectionPartition(
            provider.source_id, "flood", NOW - timedelta(days=1), NOW
        )
        with pytest.raises(CollectionProviderError) as error:
            await provider.fetch_page(part)
    assert error.value.outcome == outcome
    assert error.value.retry_after_seconds == 1800
    assert len(calls) == 1


async def test_fixed_replay_retains_reports_beyond_legacy_page_budget(tmp_path):
    from disaster_monitor.application.incidents.resumable_discovery import (
        ResumableDiscovery,
    )
    from disaster_monitor.domain.discovery import ReportingInterval
    from disaster_monitor.infrastructure.news.reliefweb_discovery import (
        ReliefWebDiscoveryFeed,
    )
    from disaster_monitor.infrastructure.operations.sqlite_collection import (
        SQLiteCollectionJournal,
    )

    calls = []

    def respond(request):
        calls.append(request)
        params = request.url.params
        if params["filter[conditions][0][value]"] != "Flood":
            return httpx.Response(200, json={"totalCount": 0, "data": []})
        offset = int(params["offset"])
        return httpx.Response(
            200,
            json={
                "totalCount": 61,
                "data": [
                    {
                        "fields": {
                            "title": "Flood in Riverton",
                            "url": f"https://reliefweb.int/node/{i}",
                            "body": (
                                "Floods struck Riverton on October 18, 2026. "
                                "Officials said two people died in the flood."
                            ),
                            "date": {
                                "original": (NOW - timedelta(hours=1)).isoformat()
                            },
                            "source": [{"name": "CONTROLLED publisher"}],
                        }
                    }
                    for i in range(offset, min(offset + 20, 61))
                ],
            },
        )

    class UnusedReader:
        async def retrieve(self, lead):
            raise AssertionError("ReliefWeb supplied article text")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        legacy = ReliefWebDiscoveryFeed(
            app_name="approved-test", client=client, minimum_request_interval=0
        )
        batches = [
            batch
            async for batch in legacy.discover(
                interval=ReportingInterval.at_start(1, NOW)
            )
        ]
        old_urls = {a.source.canonical_url for batch in batches for a in batch.articles}
        old_calls = len(calls)
        provider = ReliefWebCollectionProvider(
            app_name="approved-test", client=client, minimum_interval=0
        )
        runtime = ResumableDiscovery(
            (provider,),
            UnusedReader(),
            SQLiteCollectionJournal(tmp_path / "jobs.sqlite"),
            clock=lambda: NOW,
        )
        run = await runtime.start(1)
        await runtime.wait(run.scan_id)
        result = await runtime.get(run.scan_id)
        assert len(old_urls) == 40
        assert len(result.reports) == 61
        assert old_calls == 8
        assert len(calls) - old_calls == 10
        assert result.status == "completed"
        await runtime.aclose()


async def test_provider_queue_wait_does_not_consume_the_network_timeout():
    from disaster_monitor.infrastructure.news.collection_http import CollectionJsonHttp

    async def respond(request):
        await asyncio.sleep(0.4)
        return httpx.Response(200, json={"articles": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        http = CollectionJsonHttp(client=client, timeout_seconds=1, minimum_interval=0)
        responses = await asyncio.gather(
            *(http.get("https://provider.example/search", {}) for _ in range(3))
        )
        assert len(responses) == 3
