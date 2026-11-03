"""Geographic index breadth retains bounded, attributable publisher intake."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product
from urllib.parse import parse_qs

import httpx
import pytest

from disaster_monitor.application.incidents.collection_planning import plan_collection
from disaster_monitor.domain.collection import (
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.news.google_news_collection import (
    GoogleNewsCollectionProvider,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def geographic_countries():
    # A deterministic catalog-sized directory, independent of local downloaded
    # geography. Bound the complete frontier, not the six-country bootstrap.
    base = StaticCountryCatalog().countries()[0]
    names = [("NOR", "Norway"), ("CIV", "Côte d'Ivoire")]
    names.extend(
        (code, f"Country {code}")
        for letters in product("ABCDEFGHIJ", repeat=3)
        if (code := "".join(letters)) not in {"NOR", "CIV"}
    )
    return tuple(
        replace(base, alpha3_code=code, canonical_name=name, aliases=())
        for code, name in names[:242]
    )


async def test_every_catalog_country_has_one_seven_hazard_root_and_old_keys_survive():
    countries = geographic_countries()
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="<rss><channel/></rss>")

    baseline = GoogleNewsCollectionProvider().queries
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GoogleNewsCollectionProvider(
            countries=lambda: countries,
            client=client,
            minimum_interval=0,
            clock=lambda: NOW,
        )
        assert provider.queries[: len(baseline)] == baseline
        added = provider.queries[len(baseline) :]
        assert len(added) == len(countries) == len(set(added))
        for query in added:
            page = await provider.fetch_page(
                CollectionPartition(
                    provider.source_id, query, NOW - timedelta(days=7), NOW
                )
            )
            assert not page.leads and not page.articles
    requested = [request.url.params["q"] for request in calls]
    for country in countries:
        (query,) = [
            q for q in requested if q.startswith(f'"{country.canonical_name}" ')
        ]
        assert all(
            word in query
            for word in (
                "earthquake",
                "flood",
                "wildfire",
                "landslide",
                "cyclone",
                '"volcanic eruption"',
                "drought",
            )
        )
        assert "after:2026-09-07 before:2026-09-16" in query
    assert all(request.url.params["ceid"] == "US:en" for request in calls)


async def test_country_query_uses_catalog_text_and_rejects_unconfigured_keys():
    country = next(c for c in geographic_countries() if c.alpha3_code == "CIV")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="<rss><channel/></rss>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GoogleNewsCollectionProvider(
            countries=lambda: (country,),
            client=client,
            minimum_interval=0,
            clock=lambda: NOW,
        )
        root = CollectionPartition(
            provider.source_id, provider.queries[-1], NOW - timedelta(days=1), NOW
        )
        await provider.fetch_page(root)
        assert calls[0].url.params["q"].startswith(f'"{country.canonical_name}" ')
        with pytest.raises(CollectionProviderError, match="query"):
            await provider.fetch_page(replace(root, query="en-US|country:UNKNOWN"))
    assert len(calls) == 1


async def test_catalog_refresh_adds_roots_and_keeps_issued_query_meanings():
    countries = list(geographic_countries()[:1])
    requested = []

    def respond(request):
        requested.append(request.url.params["q"])
        return httpx.Response(200, text="<rss><channel/></rss>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GoogleNewsCollectionProvider(
            countries=lambda: tuple(countries),
            client=client,
            minimum_interval=0,
            clock=lambda: NOW,
        )
        old = provider.queries[-1]
        countries[:] = [replace(countries[0], canonical_name="Renamed Test Country")]
        new = provider.queries[-1]
        assert new != old
        for query in (old, new):
            await provider.fetch_page(
                CollectionPartition(
                    provider.source_id,
                    query,
                    NOW - timedelta(days=1),
                    NOW,
                )
            )
        assert requested[0].startswith('"Norway" ')
        assert requested[1].startswith('"Renamed Test Country" ')


async def test_reopened_provider_resolves_issued_country_work_before_planning():
    country = geographic_countries()[0]
    before = GoogleNewsCollectionProvider(countries=lambda: (country,))
    issued = before.queries[-1]
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="<rss><channel/></rss>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reopened = GoogleNewsCollectionProvider(
            countries=lambda: (country,),
            client=client,
            minimum_interval=0,
            clock=lambda: NOW,
        )
        await reopened.fetch_page(
            CollectionPartition(
                reopened.source_id,
                issued,
                NOW - timedelta(days=1),
                NOW,
            )
        )
    assert len(calls) == 1 and calls[0].url.params["q"].startswith('"Norway" ')


class GeographicReplies:
    def __init__(self):
        self.calls = []

    def respond(self, request):
        self.calls.append(request)
        if request.url.path == "/rss/search":
            if not request.url.params["q"].startswith('"Norway" '):
                return httpx.Response(200, text="<rss><channel/></rss>")
            return httpx.Response(
                200,
                text="""<rss><channel><item>
                <title>Coastal flood response continues</title>
                <link>https://news.google.com/rss/articles/CBMi_GEOGRAPHIC?oc=5</link>
                <source url="https://daily.example">Regional Daily</source>
                <pubDate>Mon, 14 Sep 2026 12:00:00 GMT</pubDate>
                </item></channel></rss>""",
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                text=(
                    '<div data-n-a-id="CBMi_GEOGRAPHIC" data-n-a-ts="123" '
                    'data-n-a-sg="public-signature"></div>'
                ),
            )
        rpc = json.loads(parse_qs(request.content.decode())["f.req"][0])[0][0]
        assert rpc[0] == "Fbv4je"
        body = json.dumps(
            [
                [
                    "wrb.fr",
                    "Fbv4je",
                    json.dumps(
                        [
                            "garturlres",
                            "https://daily.example/response",
                        ]
                    ),
                ]
            ]
        )
        return httpx.Response(200, text=")]}'\n\n123\n" + body)


async def test_full_catalog_reaches_publisher_intake_within_unchanged_phase_allowance(
    tmp_path,
):
    replies = GeographicReplies()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(replies.respond)
    ) as client:
        provider = GoogleNewsCollectionProvider(
            countries=geographic_countries,
            client=client,
            minimum_interval=0,
            clock=lambda: NOW,
        )
        interval = ReportingInterval.at_start(30, NOW)
        roots = plan_collection(interval, (provider,), observed_at=NOW)
        # The full root frontier must leave most of the 40*200 metadata allowance
        # for resolving index citations, rather than consuming it with more roots.
        assert len(roots) < 40 * 200 // 4
        path = tmp_path / "geographic.sqlite"
        store = SQLiteCollectionJournal(path, maximum_metadata_requests=1200)
        run = DiscoveryRun("geographic", interval)
        await store.attach(run, roots, now=NOW, budget=200)
        publisher = None
        for allocation in range(40):
            while work := await store.claim("search", "index", now=NOW):
                page = await provider.fetch_page(work.partition)
                assert len(replies.calls) <= (allocation + 1) * 200
                assert not page.articles
                if page.leads:
                    (lead,) = page.leads
                    assert lead.published_at is None and lead.updated_at is None
                    assert lead.canonical_url == "https://daily.example/response"
                assert await store.commit_page(work, page, now=NOW)
                publisher = await store.claim("retrieve", "publisher", now=NOW)
                if publisher:
                    break
            if publisher:
                break
            await store.finish_pass(now=NOW)
            store = SQLiteCollectionJournal(path, maximum_metadata_requests=1200)
            await store.continue_scan(run.scan_id, now=NOW, budget=200, partitions=())
        assert publisher is not None
        assert publisher.lead.canonical_url == "https://daily.example/response"
        assert allocation < 10
        assert len(replies.calls) <= (allocation + 1) * 200
        assert len(replies.calls) < 40 * 200
        assert (await store.read(run.scan_id)).interval == interval
