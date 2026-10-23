"""Publisher redirects preserve the public boundary, policy and article identity."""

from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_providers import (
    PublicCollectionArticleReader,
)
from disaster_monitor.infrastructure.news.public_documents import PublicDocumentReader


async def test_same_publisher_redirect_uses_final_article_metadata_and_original_link():
    calls = []

    def respond(request):
        calls.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "publisher.example"
        assert request.extensions["sni_hostname"] == "publisher.example"
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/news/current"})
        assert request.url.path == "/news/current"
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text="""<script type="application/ld+json">{"@type":"NewsArticle",
            "url":"https://publisher.example/news/current",
            "headline":"Flood report", "datePublished":"2026-10-22T09:00:00Z",
            "dateModified":"2026-10-23T10:00:00Z"}</script>
            <article><h1>Flood report</h1><p>Police said two people died in the flood.
            </p></article>""",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        article = await PublicCollectionArticleReader(reader=reader).retrieve(
            NewsFeedItem(
                external_id="old",
                title="Old index title",
                publisher="Publisher",
                canonical_url="https://publisher.example/old",
                published_at=None,
                updated_at=None,
                indexed_at=datetime(2026, 10, 23, tzinfo=UTC),
            )
        )
    assert article.source.canonical_url == "https://publisher.example/old"
    assert article.source.published_at == datetime(2026, 10, 22, 9, tzinfo=UTC)
    assert article.source.updated_at == datetime(2026, 10, 23, 10, tzinfo=UTC)
    assert article.indexed_at == datetime(2026, 10, 23, tzinfo=UTC)
    assert article.source.title == "Flood report"
    assert "two people died" in article.text
    assert len(calls) == 3


async def test_redirected_article_path_must_also_be_allowed_by_robots():
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(302, headers={"Location": "/private/story"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError, match="robots.*disallows"):
            await reader.read("https://publisher.example/report")
    assert calls == ["/robots.txt", "/report"]


@pytest.mark.parametrize(
    "location",
    [
        "http://publisher.example/report",
        "https://other.example/report",
        "https://user:password@publisher.example/report",
        "https://publisher.example:444/report",
        "https://127.0.0.1/report",
        "https://publisher.example/report#part",
        "/",
    ],
)
async def test_article_redirect_rejects_unsafe_or_uncoordinated_destinations(location):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"Location": location})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError):
            await reader.read("https://publisher.example/report")
    assert calls == ["/robots.txt", "/report"]


@pytest.mark.parametrize("loop", [True, False])
async def test_article_redirect_loops_and_long_chains_stop_without_retries(loop):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        target = "/0" if loop else f"/{int(request.url.path[1:]) + 1}"
        return httpx.Response(302, headers={"Location": target})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError, match="redirect"):
            await reader.read("https://publisher.example/0")
    assert len(calls) == (2 if loop else 7)


@pytest.mark.parametrize("allow", [True, False])
async def test_redirected_robots_policy_applies_to_the_original_publisher(allow):
    calls = []

    def respond(request):
        calls.append((request.headers["host"], request.url.path))
        if request.url.path == "/robots.txt":
            return httpx.Response(
                301, headers={"Location": "https://policy.example/rules"}
            )
        if request.url.path == "/rules":
            assert request.url.host == "93.184.216.35"
            assert request.extensions["sni_hostname"] == "policy.example"
            return httpx.Response(
                200, text="User-agent: *\nDisallow:" + ("" if allow else " /report")
            )
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client,
            resolver=lambda host: (
                "93.184.216.35" if host == "policy.example" else "93.184.216.34",
            ),
        )
        if allow:
            document = await reader.read("https://publisher.example/report")
            assert document.html == "<article>Report</article>"
            assert document.url == "https://publisher.example/report"
        else:
            with pytest.raises(ValueError, match="robots.*disallows"):
                await reader.read("https://publisher.example/report")
    assert calls[:2] == [
        ("publisher.example", "/robots.txt"),
        ("policy.example", "/rules"),
    ]
    assert len(calls) == (3 if allow else 2)


@pytest.mark.parametrize("addresses", [("127.0.0.1",), ("93.184.216.35", "::1")])
async def test_robots_redirect_revalidates_all_destination_addresses(addresses):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(301, headers={"Location": "https://policy.example/rules"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client,
            resolver=lambda host: (
                addresses if host == "policy.example" else ("93.184.216.34",)
            ),
        )
        with pytest.raises(ValueError, match="public addresses"):
            await reader.read("https://publisher.example/report")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [403, 429, 503])
async def test_same_host_redirect_preserves_terminal_refusals_and_retry_after(status):
    from disaster_monitor.domain.collection import CollectionProviderError

    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/old":
            return httpx.Response(302, headers={"Location": "/new"})
        return httpx.Response(status, headers={"Retry-After": "1800"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicCollectionArticleReader(
            reader=PublicDocumentReader(
                client=client, resolver=lambda host: ("93.184.216.34",)
            )
        )
        with pytest.raises(CollectionProviderError) as error:
            await reader.retrieve(
                NewsFeedItem(
                    external_id="old",
                    title="Flood",
                    publisher="Publisher",
                    canonical_url="https://publisher.example/old",
                    published_at=None,
                    updated_at=None,
                )
            )
    assert error.value.outcome == (
        "rate_limited" if status == 429 else "article_unavailable"
    )
    assert error.value.retry_after_seconds == 1800
    assert calls == ["/robots.txt", "/old", "/new"]


@pytest.mark.parametrize("kind", ["loop", "limit", "downgrade", "delay"])
async def test_robots_redirect_failures_never_reach_article_content(kind):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if kind == "loop":
            return httpx.Response(302, headers={"Location": "/robots.txt"})
        if kind == "downgrade":
            return httpx.Response(
                302, headers={"Location": "http://publisher.example/rules"}
            )
        if kind == "delay" and request.url.path == "/rules":
            return httpx.Response(200, text="User-agent: *\nDisallow:\nCrawl-delay: 1")
        target = "/rules" if kind == "delay" else f"/rules/{len(calls)}"
        return httpx.Response(302, headers={"Location": target})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError):
            await reader.read("https://publisher.example/report")
    assert "/report" not in calls
    assert len(calls) <= 6


async def test_five_redirects_are_allowed_without_losing_the_original_robots_rules():
    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        number = int(request.url.path[1:])
        if number < 5:
            return httpx.Response(308, headers={"Location": f"/{number + 1}"})
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        document = await reader.read("https://publisher.example/0")
    assert document.url == "https://publisher.example/5"
    assert document.html == "<article>Report</article>"


async def test_legacy_feed_uses_validated_document_identity_for_publication():
    from disaster_monitor.domain.discovery import ReportingInterval
    from disaster_monitor.infrastructure.news.discovery_feed import GdeltDiscoveryFeed
    from disaster_monitor.infrastructure.news.public_documents import PublicDocument

    now = datetime(2026, 10, 23, tzinfo=UTC)

    class Reader:
        async def read(self, url):
            return PublicDocument(
                """<script type="application/ld+json">{"@type":"NewsArticle",
                "url":"https://publisher.example/new", "headline":"Flood report",
                "datePublished":"2026-10-22T09:00:00Z"}</script>
                <article><p>Police said two people died in the flood.</p></article>""",
                "https://publisher.example/new",
            )

    def respond(request):
        if request.url.params["query"] != "flood":
            return httpx.Response(200, json={"articles": []})
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://publisher.example/old",
                        "title": "Flood report",
                        "domain": "publisher.example",
                        "seendate": "20261022090000",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = GdeltDiscoveryFeed(
            client=client, reader=Reader(), minimum_request_interval=0
        )
        batches = [
            batch
            async for batch in feed.discover(
                interval=ReportingInterval.at_start(1, now)
            )
        ]
        await feed.aclose()
    articles = [article for batch in batches for article in batch.articles]
    assert len(articles) == 1
    assert articles[0].source.canonical_url == "https://publisher.example/old"
    assert articles[0].source.published_at == datetime(2026, 10, 22, 9, tzinfo=UTC)


def test_redirected_article_may_keep_its_original_canonical_identity():
    from disaster_monitor.infrastructure.news.discovery_parser import (
        parse_discovery_article,
    )

    article = parse_discovery_article(
        """<script type="application/ld+json">{"@type":"NewsArticle",
        "url":"https://publisher.example/old", "headline":"Flood report",
        "datePublished":"2026-10-22T09:00:00Z"}</script>
        <article><p>Police reported two flood deaths.</p></article>""",
        url="https://publisher.example/old",
        document_url="https://publisher.example/new",
        title="Flood",
        publisher="Publisher",
        retrieved_at=datetime(2026, 10, 23, tzinfo=UTC),
        indexed_at=None,
    )
    assert article.source.canonical_url == "https://publisher.example/old"
    assert article.source.published_at == datetime(2026, 10, 22, 9, tzinfo=UTC)


def test_conflicting_article_identities_across_redirect_stay_unresolved():
    from disaster_monitor.infrastructure.news.discovery_parser import (
        parse_discovery_article,
    )

    article = parse_discovery_article(
        """<script type="application/ld+json">[
        {"@type":"NewsArticle", "url":"https://publisher.example/old",
        "headline":"Older flood", "datePublished":"2025-10-22T09:00:00Z"},
        {"@type":"NewsArticle", "url":"https://publisher.example/new",
        "headline":"Recent quake", "datePublished":"2026-10-22T09:00:00Z"}
        ]</script>""",
        url="https://publisher.example/old",
        document_url="https://publisher.example/new",
        title="Index title",
        publisher="Publisher",
        retrieved_at=datetime(2026, 10, 23, tzinfo=UTC),
        indexed_at=None,
    )
    assert article.source.published_at is None
    assert article.event_time is None
