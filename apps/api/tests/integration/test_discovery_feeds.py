from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.domain.discovery import ReportingInterval
from disaster_monitor.infrastructure.news.discovery_feed import GdeltDiscoveryFeed
from disaster_monitor.infrastructure.news.discovery_parser import (
    parse_discovery_article,
)
from disaster_monitor.infrastructure.news.public_documents import PublicDocumentReader

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def test_unrelated_event_and_update_metadata_never_become_onset_or_publication():
    report = parse_discovery_article(
        """<meta property="article:modified_time" content="2026-10-17T10:00:00Z">
        <script type="application/ld+json">{"@type":"Event",
        "startDate":"2026-09-01T10:00:00Z",
        "location":{"geo":{"latitude":12,"longitude":105}}}</script>
        <p>Two people died in an unrelated sidebar.</p>""",
        url="https://unfamiliar.example/story",
        title="Flood in Riverton",
        publisher="Unfamiliar News",
        retrieved_at=NOW,
        indexed_at=NOW,
    )
    assert report.source.published_at is None
    assert report.source.updated_at is not None
    assert report.event_time is None
    assert report.geometry is None
    assert not report.text


@pytest.mark.parametrize("kind", ["redirect", "type", "size"])
async def test_article_boundary_rejects_redirects_non_html_and_oversize(kind):
    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if kind == "redirect":
            return httpx.Response(
                302, headers={"location": "https://127.0.0.1/private"}
            )
        if kind == "type":
            return httpx.Response(200, headers={"content-type": "application/pdf"})
        return httpx.Response(
            200, headers={"content-type": "text/html", "content-length": "1000001"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError):
            await reader.read("https://publisher.example/report")


async def test_article_budget_attempts_every_category_and_marks_dropped_partitions():
    queries = []

    def respond(request):
        query = request.url.params["query"]
        queries.append(query)
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": f"https://publisher.example/{len(queries)}",
                        "title": f"{query} report",
                        "domain": "publisher.example",
                        "seendate": "20261017T100000Z",
                    }
                ]
            },
        )

    class Reader:
        async def read(self, url):
            return (
                '<meta property="article:published_time" '
                'content="2026-10-17T10:00:00Z">'
            )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = GdeltDiscoveryFeed(
            client=client,
            reader=Reader(),
            maximum_records=1,
            maximum_articles=7,
            minimum_request_interval=0,
        )
        batches = [
            batch
            async for batch in feed.discover(
                interval=ReportingInterval.at_start(7, NOW)
            )
        ]
    assert len(set(queries)) == 7
    assert sum(len(batch.articles) for batch in batches) == 7
    assert any(batch.truncated for batch in batches)


def test_article_dates_body_and_event_metadata_are_distinct():
    report = parse_discovery_article(
        """<html><meta property="article:published_time" content="2026-10-16T10:00:00Z">
    <meta property="article:modified_time" content="2026-10-17T10:00:00Z">
    <script type="application/ld+json">{"@type":"NewsArticle","about":{"@type":"Event","@id":"https://events.example/flood-1","startDate":"2026-09-01T10:00:00Z","location":{"name":"Riverton","geo":{"latitude":12,"longitude":105}}},"isBasedOn":"https://wire.example/story-1"}</script>
    <article><p>Officials say two people died.</p></article>
    <script>bad text</script></html>""",
        url="https://unfamiliar.example/report",
        title="Flood in Riverton",
        publisher="Unfamiliar News",
        retrieved_at=NOW,
        indexed_at=NOW,
    )
    assert report.source.published_at == datetime(2026, 10, 16, 10, tzinfo=UTC)
    assert report.source.updated_at == datetime(2026, 10, 17, 10, tzinfo=UTC)
    assert report.indexed_at == NOW
    assert report.event_time == datetime(2026, 9, 1, 10, tzinfo=UTC)
    assert report.geometry.coordinates[0].latitude == 12
    assert report.text == "Officials say two people died."
    assert report.origin == "https://wire.example/story-1"


@pytest.mark.parametrize(
    "robots_policy",
    [
        "User-agent: *\nDisallow: /",
        "User-agent: *\nDisallow:\nCrawl-delay: 1",
    ],
)
async def test_public_article_reader_blocks_private_destinations_and_robots_denials(
    robots_policy,
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            text=robots_policy,
            headers={"content-type": "text/plain"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("127.0.0.1",)
        )
        with pytest.raises(ValueError):
            await reader.read("https://publisher.example/report")
        assert not calls
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError, match="robots"):
            await reader.read("https://publisher.example/report")
        assert len(calls) == 1


async def test_challenge_response_is_not_successful_article_access():
    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow:",
                headers={"content-type": "text/plain"},
            )
        return httpx.Response(
            202,
            text='<div id="challenge-container"></div>',
            headers={"content-type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError, match="challenge|incomplete"):
            await reader.read("https://publisher.example/report")


async def test_gdelt_partitions_caps_and_preserves_partial_batches():
    queries = []

    def respond(request):
        queries.append(request.url.params["query"])
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://publisher.example/story",
                        "title": "Drought report",
                        "domain": "publisher.example",
                        "seendate": "20261017T100000Z",
                    }
                ]
            },
        )

    class Reader:
        async def read(self, url):
            return (
                '<meta property="article:published_time" '
                'content="2026-10-17T10:00:00Z"><p>Drought continues.</p>'
            )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        feed = GdeltDiscoveryFeed(
            client=client,
            reader=Reader(),
            maximum_records=1,
            maximum_queries=8,
            minimum_request_interval=0,
        )
        batches = [
            batch
            async for batch in feed.discover(
                interval=ReportingInterval.at_start(7, NOW)
            )
        ]
    assert any("drought" in query for query in queries)
    assert len(queries) <= 8
    assert any(batch.truncated for batch in batches)
    assert any(batch.articles for batch in batches)
    assert (
        batches[0].articles[0].source.published_at != batches[0].articles[0].indexed_at
        or batches[0].articles[0].source.published_at is not None
    )
