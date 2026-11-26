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
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
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
        assert allocation <= 1
        assert len(replies.calls) <= (allocation + 1) * 200
        assert len(replies.calls) <= 2 * 200
        assert (await store.read(run.scan_id)).interval == interval


async def test_later_attached_month_gets_root_searches_in_every_week(tmp_path):
    async with httpx.AsyncClient() as client:
        provider = GoogleNewsCollectionProvider(
            countries=geographic_countries, client=client
        )
        short = DiscoveryRun("short", ReportingInterval.at_start(1, NOW))
        month = DiscoveryRun("month", ReportingInterval.at_start(30, NOW))
        short_roots = plan_collection(short.interval, (provider,), observed_at=NOW)
        month_roots = plan_collection(month.interval, (provider,), observed_at=NOW)
        weeks = sorted({partition.start for partition in month_roots}, reverse=True)
        budget = len(weeks) + 3
        path = tmp_path / "windows.sqlite"
        journal = SQLiteCollectionJournal(path)
        await journal.attach(short, short_roots, now=NOW, budget=budget)
        await journal.attach(month, month_roots, now=NOW, budget=budget)

        # The shorter scan inserted its whole current-week queue first. An index
        # turns still reach each older week before draining the current week.
        visited = []
        for _ in range(budget):
            journal = SQLiteCollectionJournal(path)
            work = await journal.claim("search", "index", now=NOW)
            assert work is not None and work.partition is not None
            visited.append(work.partition.start)
            assert await journal.commit_page(work, CollectionPage(), now=NOW)

        assert visited == [weeks[0]] * 4 + weeks[1:]
        assert await journal.claim("search", "index", now=NOW) is None
        assert (await journal.read(short.scan_id)).interval == short.interval
        assert (await journal.read(month.scan_id)).interval == month.interval


@pytest.mark.parametrize("continued", [False, True])
async def test_small_google_allowance_reaches_multiple_markets_and_all_weeks(
    tmp_path, continued
):
    budget = 47
    async with httpx.AsyncClient() as client:
        provider = GoogleNewsCollectionProvider(client=client)
        interval = ReportingInterval.at_start(30, NOW)
        roots = plan_collection(interval, (provider,), observed_at=NOW)
        journal = SQLiteCollectionJournal(tmp_path / "regional.sqlite")
        initial = roots
        if continued:
            initial = tuple(
                replace(root, window_query_rank=root.window_query_rank + len(roots))
                if not root.query.startswith("en-US|")
                else root
                for root in roots
            )
        await journal.attach(
            DiscoveryRun("month", interval), initial, now=NOW, budget=budget
        )
        if continued:
            await journal.finish_pass(now=NOW)
            journal = SQLiteCollectionJournal(tmp_path / "regional.sqlite")
            await journal.continue_scan(
                "month", now=NOW, budget=budget, partitions=roots
            )

        claimed_roots = []
        citation_pages = 0
        for _ in range(budget):
            work = await journal.claim("search", "index", now=NOW)
            assert work is not None and work.partition is not None
            partition = work.partition
            if partition.depth:
                citation_pages += 1
                page = CollectionPage(
                    next_cursor=None if partition.cursor else "fetched-parameters"
                )
            else:
                claimed_roots.append(partition)
                citation = replace(
                    partition,
                    query=f"google-article:fixture-{len(claimed_roots)}",
                    depth=1,
                    defer_initial_request=True,
                    shared_resource=True,
                    window_query_rank=None,
                )
                page = CollectionPage(children=(citation,))
            assert await journal.commit_page(work, page, now=NOW)

        assert await journal.claim("search", "past-budget", now=NOW) is None
        assert citation_pages == 31
        assert {root.start for root in claimed_roots} == {root.start for root in roots}
        current_week = max(root.start for root in roots)
        current_queries = {
            root.query for root in claimed_roots if root.start == current_week
        }
        assert {"en-US|earthquake", "en-US|flood", "en-US|wildfire"} <= current_queries
        assert len({query.split("|")[0] for query in current_queries}) >= 6
        assert 'en-US|"natural disasters" report' in current_queries


async def test_weekly_google_report_root_searches_for_publication_evidence():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, text="<rss><channel/></rss>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        interval = ReportingInterval.at_start(30, NOW)
        roots = plan_collection(interval, (provider,), observed_at=NOW)
        current_week = max(root.start for root in roots)
        report_roots = [
            r for r in roots if r.query == 'en-US|"natural disasters" report'
        ]
        assert {r.start for r in report_roots} == {r.start for r in roots}
        root = next(r for r in report_roots if r.start == current_week)
        assert 6 <= root.window_query_rank <= 10
        await provider.fetch_page(root)
    (request,) = calls
    assert request.url.params["ceid"] == "US:en"
    assert request.url.params["q"].startswith('"natural disasters" report after:')


@pytest.mark.parametrize("resume_retained", [False, True])
async def test_historical_report_roots_run_within_a_bounded_allocation(
    tmp_path, resume_retained
):
    provider = GoogleNewsCollectionProvider()
    interval = ReportingInterval.at_start(30, NOW)
    roots = plan_collection(interval, (provider,), observed_at=NOW)
    report_query = 'en-US|"natural disasters" report'
    current_week = max(root.start for root in roots)
    budget = 90
    path = tmp_path / "historical-reports.sqlite"
    journal = SQLiteCollectionJournal(path)
    retained = tuple(
        replace(root, window_query_rank=123)
        if root.start < current_week and root.query == report_query
        else root
        for root in roots
    )
    await journal.attach(
        DiscoveryRun("month", interval),
        retained if resume_retained else roots,
        now=NOW,
        budget=budget,
    )
    if resume_retained:
        first = await journal.claim("search", "index", now=NOW)
        assert first is not None and first.partition is not None
        await journal.commit_page(first, CollectionPage(), now=NOW)
        await journal.finish_pass(now=NOW)
        journal = SQLiteCollectionJournal(path)
        await journal.continue_scan("month", now=NOW, budget=budget, partitions=roots)

    claimed_roots = []
    for _ in range(budget):
        work = await journal.claim("search", "index", now=NOW)
        assert work is not None and work.partition is not None
        part = work.partition
        if part.depth:
            page = CollectionPage(
                next_cursor=None if part.cursor else "received-parameters"
            )
        else:
            claimed_roots.append(part)
            page = CollectionPage(
                children=(
                    replace(
                        part,
                        query=f"google-article:fixture-{len(claimed_roots)}",
                        depth=1,
                        defer_initial_request=True,
                        shared_resource=True,
                        window_query_rank=None,
                    ),
                )
            )
        assert await journal.commit_page(work, page, now=NOW)
    assert await journal.claim("search", "index", now=NOW) is None
    assert {root.start for root in claimed_roots if root.query == report_query} == {
        root.start for root in roots
    }
    if resume_retained:
        assert first.partition.key not in {root.key for root in claimed_roots}


async def test_google_report_fallback_claims_a_bounded_turn_amid_index_work(tmp_path):
    interval = ReportingInterval.at_start(30, NOW)
    provider = GoogleNewsCollectionProvider()
    roots = plan_collection(interval, (provider,), observed_at=NOW)
    journal = SQLiteCollectionJournal(tmp_path / "report-recovery.sqlite")
    await journal.attach(DiscoveryRun("month", interval), roots, now=NOW, budget=14)
    first = await journal.claim("search", "google", now=NOW)
    lead_url = "https://publisher.example/report.pdf"
    citations = tuple(
        replace(
            first.partition,
            query=f"google-article:{i}",
            depth=1,
            defer_initial_request=True,
            window_query_rank=None,
            priority=0,
        )
        for i in range(20)
    )
    lead = NewsFeedItem("reference", "Publisher", "Full report", lead_url, None, None)
    await journal.commit_page(
        first, CollectionPage(leads=(lead,), children=citations), now=NOW
    )
    retrieval = await journal.claim("retrieve", "publisher", now=NOW)
    alternate = CollectionPartition(
        provider.source_id,
        "River Basin Flood Recovery Assessment",
        interval.start,
        NOW,
        alternate_for=lead_url,
        publisher_document_alternate=True,
    )
    await journal.fail(
        retrieval,
        now=NOW,
        outcome="article_unavailable",
        detail="Controlled absence",
        alternates=(alternate,),
    )
    claimed = []
    for _ in range(13):
        work = await journal.claim("search", "google", now=NOW)
        claimed.append(work.partition)
        await journal.commit_page(work, CollectionPage(), now=NOW)
    assert claimed[0] == alternate
    assert claimed.count(alternate) == 1
    assert sum(part.depth == 1 for part in claimed) == 8
