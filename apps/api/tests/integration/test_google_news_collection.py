"""Google metadata steps never hide fan-out or replace publisher evidence."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from disaster_monitor.domain.collection import (
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.news.google_news_collection import (
    GoogleNewsCollectionProvider,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


class GoogleReplies:
    def __init__(self, *, target="https://daily.example/story", status=200):
        self.calls = []
        self.target = target
        self.status = status

    def respond(self, request):
        self.calls.append(request)
        assert request.url.host == "news.google.com"
        if self.status != 200:
            return httpx.Response(self.status, headers={"Retry-After": "60"})
        if request.url.path == "/rss/search":
            return httpx.Response(
                200,
                text="""<rss><channel>
                <item><title>Earthquake survivors seek shelter</title>
                <link>https://news.google.com/rss/articles/CBMi_TEST_A?oc=5</link>
                <source url="https://daily.example">Regional Daily</source>
                <pubDate>Mon, 14 Sep 2026 12:00:00 GMT</pubDate></item>
                <item><title>Recovery continues</title>
                <link>https://news.google.com/rss/articles/CBMi_TEST_B?oc=5</link>
                <source url="https://daily.example">Regional Daily</source></item>
                </channel></rss>""",
            )
        if request.method == "GET":
            identity = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                text=(
                    f'<div data-n-a-id="{identity}" data-n-a-ts="123" '
                    'data-n-a-sg="public-signature"></div>'
                ),
            )
        assert request.method == "POST"
        form = parse_qs(request.content.decode())
        rpc = json.loads(form["f.req"][0])[0][0]
        assert rpc[0] == "Fbv4je"
        operation = json.loads(rpc[1])
        assert operation[0] == "garturlreq" and operation[3:] == [
            123,
            "public-signature",
        ]
        payload = json.dumps(
            [["wrb.fr", "Fbv4je", json.dumps(["garturlres", self.target])]]
        )
        return httpx.Response(200, text=")]}'\n\n123\n" + payload)


def partition(provider):
    return CollectionPartition(
        provider.source_id,
        provider.queries[0],
        NOW - timedelta(days=7),
        NOW,
        generation="controlled",
        priority=1,
    )


async def test_feed_children_and_resolution_are_durable_separately_metered_steps(
    tmp_path,
):
    replies = GoogleReplies()
    path = tmp_path / "collection.sqlite"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(replies.respond)
    ) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        root = partition(provider)
        store = SQLiteCollectionJournal(path, maximum_metadata_requests=10)
        run = DiscoveryRun("view", ReportingInterval.at_start(7, NOW))
        await store.attach(run, (root,), now=NOW, budget=2)
        work = await store.claim("search", "feed", now=NOW)
        page = await provider.fetch_page(work.partition)
        assert len(replies.calls) == 1 and len(page.children) == 2
        assert not page.leads and not page.articles
        assert await store.commit_page(work, page, now=NOW)
        child = await store.claim("search", "public-page", now=NOW)
        page = await provider.fetch_page(child.partition)
        assert len(replies.calls) == 2 and page.next_cursor and not page.leads
        assert await store.commit_page(child, page, now=NOW)
        assert await store.claim("search", "no-extra", now=NOW) is None
        await store.finish_pass(now=NOW)

        restarted = SQLiteCollectionJournal(path, maximum_metadata_requests=10)
        await restarted.continue_scan(run.scan_id, now=NOW, budget=2, partitions=())
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        rpc_work = await restarted.claim("search", "resolution", now=NOW)
        assert rpc_work.work_id == child.work_id
        page = await provider.fetch_page(rpc_work.partition)
        assert len(replies.calls) == 3 and replies.calls[-1].method == "POST"
        (lead,) = page.leads
        assert lead.canonical_url == "https://daily.example/story"
        assert lead.publisher == "Regional Daily"
        assert lead.published_at is None and lead.updated_at is None
        assert lead.indexed_at == datetime(2026, 9, 14, 12, tzinfo=UTC)
        assert not page.articles
        assert await restarted.commit_page(rpc_work, page, now=NOW)
        progress = (await restarted.snapshot(run.scan_id, now=NOW)).progress
        assert dict(progress.provider_requests)[provider.source_id] == len(
            replies.calls
        )
        assert progress.leads_acquired == 1
        publisher = await restarted.claim("retrieve", "publisher", now=NOW)
        assert publisher.lead == lead


@pytest.mark.parametrize(
    "target",
    [
        "https://unrelated.example/story",
        "http://daily.example/story",
        "https://daily.example@127.0.0.1/private",
        "https://daily.example/",
    ],
)
async def test_resolution_cannot_admit_an_unrelated_unsafe_or_root_destination(target):
    replies = GoogleReplies(target=target)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(replies.respond)
    ) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        child = (await provider.fetch_page(partition(provider))).children[0]
        page = await provider.fetch_page(child)
        with pytest.raises(CollectionProviderError, match="publisher|destination"):
            await provider.fetch_page(replace(child, cursor=page.next_cursor))
    assert len(replies.calls) == 3


@pytest.mark.parametrize(
    "status,outcome", [(403, "access_refused"), (429, "rate_limited")]
)
async def test_provider_policy_boundary_survives_without_retry_or_publisher_request(
    status, outcome
):
    replies = GoogleReplies(status=status)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(replies.respond)
    ) as client:
        provider = GoogleNewsCollectionProvider(client=client, minimum_interval=0)
        with pytest.raises(CollectionProviderError) as caught:
            await provider.fetch_page(partition(provider))
    assert caught.value.outcome == outcome
    assert caught.value.retry_after_seconds == 60
    assert len(replies.calls) == 1


async def test_malformed_internal_state_cannot_issue_a_network_request():
    replies = GoogleReplies()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(replies.respond)
    ) as client:
        provider = GoogleNewsCollectionProvider(client=client, minimum_interval=0)
        with pytest.raises(CollectionProviderError, match="continuation"):
            await provider.fetch_page(
                replace(
                    partition(provider),
                    cursor='{"stage":"rpc","url":"http://localhost/"}',
                )
            )
    assert not replies.calls


async def test_public_page_keeps_locale_query_and_refreshes_stale_metadata():
    replies = GoogleReplies()
    clock = [NOW]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(replies.respond)
    ) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: clock[0]
        )
        child = (await provider.fetch_page(partition(provider))).children[0]
        page = await provider.fetch_page(child)
        assert dict(replies.calls[-1].url.params) == {
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }
        clock[0] += timedelta(minutes=3)
        refreshed = await provider.fetch_page(replace(child, cursor=page.next_cursor))
        assert replies.calls[-1].method == "GET" and len(replies.calls) == 3
        assert not refreshed.leads
        resolved = await provider.fetch_page(
            replace(child, cursor=refreshed.next_cursor)
        )
        assert replies.calls[-1].method == "POST" and len(replies.calls) == 4
        assert len(resolved.leads) == 1


@pytest.mark.parametrize(
    "target,allowed",
    [
        ("https://news.google.com/articles/CBMi_TEST_A?hl=en-US", True),
        ("https://unrelated.example/story", False),
    ],
)
async def test_redirect_requires_a_new_metered_step_and_refuses_unrelated_hosts(
    target, allowed
):
    replies = GoogleReplies()

    def respond(request):
        if request.url.path == "/rss/articles/CBMi_TEST_A":
            replies.calls.append(request)
            return httpx.Response(302, headers={"Location": target})
        return replies.respond(request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), follow_redirects=True
    ) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        child = (await provider.fetch_page(partition(provider))).children[0]
        if allowed:
            page = await provider.fetch_page(child)
            assert len(replies.calls) == 2 and page.next_cursor and not page.leads
            page = await provider.fetch_page(replace(child, cursor=page.next_cursor))
            assert len(replies.calls) == 3 and page.next_cursor and not page.leads
        else:
            with pytest.raises(CollectionProviderError, match="redirect"):
                await provider.fetch_page(child)
            assert len(replies.calls) == 2


@pytest.mark.parametrize(
    "markup",
    [
        '<div data-n-a-id="DIFFERENT" data-n-a-ts="123" data-n-a-sg="s"></div>',
        '<div data-n-a-id="CBMi_TEST_A" data-n-a-ts="123" data-n-a-sg="a"></div>'
        '<div data-n-a-id="CBMi_TEST_A" data-n-a-ts="123" data-n-a-sg="b"></div>',
        '<div data-n-a-id="CBMi_TEST_A" data-n-a-ts="'
        + "9" * 5000
        + '" data-n-a-sg="s"></div>',
    ],
)
async def test_missing_conflicting_or_unbounded_public_metadata_fails_closed(markup):
    replies = GoogleReplies()

    def respond(request):
        if request.url.path == "/rss/search":
            return replies.respond(request)
        replies.calls.append(request)
        return httpx.Response(200, text=markup)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        child = (await provider.fetch_page(partition(provider))).children[0]
        with pytest.raises(CollectionProviderError, match="metadata"):
            await provider.fetch_page(child)
    assert len(replies.calls) == 2


async def test_dated_alternative_keeps_lineage_and_meters_each_resolution_step(
    tmp_path,
):
    replies = GoogleReplies()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(replies.respond)
    ) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        assert provider.supports_alternates
        root = replace(
            partition(provider),
            query='earthquake "Lakeview"',
            alternate_for="https://daily.example/inaccessible",
            priority=0,
        )
        store = SQLiteCollectionJournal(
            tmp_path / "alternate.sqlite", maximum_metadata_requests=4
        )
        run = DiscoveryRun("alternate", ReportingInterval.at_start(30, NOW))
        await store.attach(run, (root,), now=NOW, budget=4)
        feed = await store.claim("search", "feed", now=NOW)
        page = await provider.fetch_page(feed.partition)
        assert len(replies.calls) == 1
        assert (
            replies.calls[0].url.params["q"]
            == 'earthquake "Lakeview" after:2026-09-07 before:2026-09-16'
        )
        assert all(
            c.alternate_for == root.alternate_for and not c.shared_resource
            for c in page.children
        )
        assert await store.commit_page(feed, page, now=NOW)
        first = await store.claim("search", "page", now=NOW)
        assert first.partition.defer_initial_request and first.partition.priority == 0
        page = await provider.fetch_page(first.partition)
        assert len(replies.calls) == 2 and page.next_cursor
        assert await store.commit_page(first, page, now=NOW)
        store = SQLiteCollectionJournal(
            tmp_path / "alternate.sqlite", maximum_metadata_requests=4
        )
        rpc = await store.claim("search", "rpc", now=NOW)
        assert rpc.work_id == first.work_id
        assert (
            rpc.partition.priority == 1
            and rpc.partition.alternate_for == root.alternate_for
        )
        page = await provider.fetch_page(rpc.partition)
        assert len(replies.calls) == 3 and replies.calls[-1].method == "POST"
        assert await store.commit_page(rpc, page, now=NOW)
        retrieval = await store.claim("retrieve", "body", now=NOW)
        assert retrieval.alternate_depth == 1
        assert (
            retrieval.lead.published_at is None
            and retrieval.lead.indexed_at is not None
        )


@pytest.mark.parametrize(
    "query",
    ["earthquake after:2020-01-01", "https://daily.example", "word " * 33, "x" * 301],
)
async def test_alternative_query_bounds_cannot_override_dates_or_add_urls(query):
    replies = GoogleReplies()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(replies.respond)
    ) as client:
        provider = GoogleNewsCollectionProvider(
            client=client, minimum_interval=0, clock=lambda: NOW
        )
        root = replace(
            partition(provider),
            query=query,
            alternate_for="https://daily.example/inaccessible",
        )
        with pytest.raises(CollectionProviderError):
            await provider.fetch_page(root)
    assert not replies.calls
