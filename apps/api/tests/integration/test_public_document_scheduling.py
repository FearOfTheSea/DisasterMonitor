"""Robots timing is honored across requests and durable-reader restarts."""

from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.domain.collection import CollectionProviderError
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_providers import (
    PublicCollectionArticleReader,
)
from disaster_monitor.infrastructure.news.public_documents import PublicDocumentReader
from disaster_monitor.infrastructure.operations.sqlite_public_document_access import (
    SQLitePublicDocumentAccess,
)


def scheduled_reader(path, client, now, sleeps, *, timeout=15):
    async def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    return PublicDocumentReader(
        client=client,
        resolver=lambda host: ("93.184.216.34",),
        access=SQLitePublicDocumentAccess(path),
        clock=lambda: now[0],
        sleep=sleep,
        timeout_seconds=timeout,
    )


def lead(host="publisher.example"):
    return NewsFeedItem("one", host, "Flood", f"https://{host}/story", None, None)


async def test_short_crawl_delay_paces_robots_article_redirect_and_restart(tmp_path):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append((request.url.path, now[0]))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\nCrawl-delay: 2")
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new"})
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        path = tmp_path / "schedule.sqlite"
        first = scheduled_reader(path, client, now, sleeps)
        document = await first.read("https://publisher.example/old")
        assert document.url == "https://publisher.example/new"
        restarted = scheduled_reader(path, client, now, sleeps)
        await restarted.read("https://publisher.example/another")
    assert [path for path, _ in calls] == ["/robots.txt", "/old", "/new", "/another"]
    assert all(
        later[1] - earlier[1] >= 2
        for earlier, later in zip(calls, calls[1:], strict=False)
    )
    assert sum(sleeps) >= 6


async def test_long_policy_wait_defers_then_uses_cached_rules_after_restart(tmp_path):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append((request.url.path, now[0]))
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nDisallow:\nCrawl-delay: 600"
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text="""
        <meta property="article:published_time" content="2026-10-22T09:00:00Z">
        <article><p>Police reported two flood deaths.</p></article>""",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        path = tmp_path / "schedule.sqlite"
        reader = PublicCollectionArticleReader(
            reader=scheduled_reader(path, client, now, sleeps)
        )
        with pytest.raises(CollectionProviderError) as error:
            await reader.retrieve(lead())
        assert error.value.outcome == "policy_deferred"
        assert error.value.retry_after_seconds >= 600
        assert calls == [("/robots.txt", 1000.0)]
        assert not sleeps
        now[0] += error.value.retry_after_seconds
        restarted = PublicCollectionArticleReader(
            reader=scheduled_reader(path, client, now, sleeps)
        )
        article = await restarted.retrieve(lead())
    assert article.source.published_at == datetime(2026, 10, 22, 9, tzinfo=UTC)
    assert [path for path, _ in calls] == ["/robots.txt", "/story"]


@pytest.mark.parametrize(
    "policy,minimum",
    [
        ("Request-rate: 2/10", 5),
        ("Crawl-delay: 0.5", 0.5),
        ("Crawl-delay: 2\nRequest-rate: 1/4", 4),
    ],
)
async def test_request_rate_and_delay_use_the_more_conservative_spacing(
    tmp_path, policy, minimum
):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append(now[0])
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n" + policy)
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await scheduled_reader(tmp_path / "schedule.sqlite", client, now, sleeps).read(
            "https://publisher.example/story"
        )
    assert calls[1] - calls[0] >= minimum


async def test_cached_denial_is_applied_to_every_new_path(tmp_path):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nDisallow: /private\nCrawl-delay: 2"
            )
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        path = tmp_path / "schedule.sqlite"
        await scheduled_reader(path, client, now, sleeps).read(
            "https://publisher.example/story"
        )
        with pytest.raises(ValueError, match="disallows"):
            await scheduled_reader(path, client, now, sleeps).read(
                "https://publisher.example/private"
            )
    assert calls == ["/robots.txt", "/story"]


async def test_policy_refresh_after_expiry_cannot_reuse_an_old_allow(tmp_path):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            rule = " /" if now[0] > 4000 else ""
            return httpx.Response(200, text="User-agent: *\nDisallow:" + rule)
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        path = tmp_path / "schedule.sqlite"
        await scheduled_reader(path, client, now, sleeps).read(
            "https://publisher.example/story"
        )
        now[0] += 3601
        with pytest.raises(ValueError, match="disallows"):
            await scheduled_reader(path, client, now, sleeps).read(
                "https://publisher.example/another"
            )
    assert calls == ["/robots.txt", "/story", "/robots.txt"]


@pytest.mark.parametrize("robots_redirect", [False, True])
async def test_long_wait_after_redirect_resumes_without_repeating_the_same_hop(
    tmp_path,
    robots_redirect,
):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            if robots_redirect:
                return httpx.Response(301, headers={"Location": "/rules"})
            return httpx.Response(200, text="User-agent: *\nDisallow:\nCrawl-delay: 10")
        if request.url.path == "/rules":
            return httpx.Response(200, text="User-agent: *\nDisallow:\nCrawl-delay: 10")
        if request.url.path == "/story":
            return httpx.Response(301, headers={"Location": "/new"})
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text="""
        <meta property="article:published_time" content="2026-10-22T09:00:00Z">
        <article><p>Police reported two flood deaths.</p></article>""",
        )

    path = tmp_path / "schedule.sqlite"
    if robots_redirect:
        access = SQLitePublicDocumentAccess(path)
        await access.remember_robots("publisher.example", "expired", 10, now=-3000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        article = None
        for _ in range(5):
            reader = PublicCollectionArticleReader(
                reader=scheduled_reader(path, client, now, sleeps)
            )
            try:
                article = await reader.retrieve(lead())
                break
            except CollectionProviderError as error:
                assert error.outcome == "policy_deferred"
                now[0] += max(900, error.retry_after_seconds)
    assert article is not None
    assert article.source.canonical_url == "https://publisher.example/story"
    assert calls == (
        ["/robots.txt", "/rules", "/story", "/new"]
        if robots_redirect
        else ["/robots.txt", "/story", "/new"]
    )


@pytest.mark.parametrize(
    "media_type", ["text/html", " text/html ; charset=utf-8", "application/xhtml+xml"]
)
async def test_html_robots_challenge_is_never_cached_as_an_allow_policy(
    tmp_path,
    media_type,
):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(
            200,
            headers={"Content-Type": media_type},
            text="<html>Checking your browser</html>",
        )

    path = tmp_path / "schedule.sqlite"
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="robots"):
            await scheduled_reader(path, client, now, sleeps).read(
                "https://publisher.example/story"
            )
    assert calls == ["/robots.txt"]
    assert (
        await SQLitePublicDocumentAccess(path).robots("publisher.example", now=now[0])
        is None
    )


async def test_minute_request_rate_is_deferred_without_an_article_request(tmp_path):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow:\nRequest-rate: 2/1m")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicCollectionArticleReader(
            reader=scheduled_reader(tmp_path / "access.sqlite", client, now, sleeps)
        )
        with pytest.raises(CollectionProviderError) as error:
            await reader.retrieve(lead())
    assert error.value.outcome == "policy_deferred"
    assert error.value.retry_after_seconds == 30
    assert calls == ["/robots.txt"] and not sleeps


@pytest.mark.parametrize(
    "policy", ["Visit-time: 0100-0200", "Request-rate: 2/10 0100-0200"]
)
async def test_unsupported_access_hours_are_never_ignored(tmp_path, policy):
    now, sleeps, calls = [1000.0], [], []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow:\n" + policy)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = scheduled_reader(tmp_path / "access.sqlite", client, now, sleeps)
        with pytest.raises(ValueError, match="access hours"):
            await reader.read("https://publisher.example/story")
    assert calls == ["/robots.txt"] and not sleeps
