"""Public retrieval applies publisher wildcard, encoding and timing restrictions."""

import httpx
import pytest

from disaster_monitor.infrastructure.news.public_documents import PublicDocumentReader


@pytest.mark.parametrize(
    "policy,path,allowed",
    [
        ("Disallow: /private/*", "/private/story", False),
        ("Disallow: /*.pdf$", "/story.pdf", False),
        ("Disallow: /*.pdf$", "/story.pdf?view=html", True),
        ("Disallow: /archive/*\nAllow: /archive/open/", "/archive/open/story", True),
        ("Disallow: /private/%66ile", "/private/file", False),
        ("Disallow: /private/%2Fsecret", "/private/%2fsecret", False),
        ("Disallow: /café/", "/caf%C3%A9/story", False),
    ],
)
async def test_publisher_rules_govern_the_actual_requested_path(policy, path, allowed):
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\n" + policy)
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        if allowed:
            assert (
                await reader.read("https://publisher.example" + path)
            ).html == "<article>Report</article>"
        else:
            with pytest.raises(ValueError, match="disallows"):
                await reader.read("https://publisher.example" + path)
    assert len(calls) == (2 if allowed else 1)


async def test_multiple_matching_crawler_groups_are_combined():
    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="""User-agent: DisasterMonitorDiscovery
Disallow: /first

User-agent: disastermonitordiscovery
Disallow: /second
""",
            )
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError, match="disallows"):
            await reader.read("https://publisher.example/second")


async def test_fractional_delay_still_requires_configured_scheduling():
    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nDisallow:\nCrawl-delay: 0.5"
            )
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="<article>Report</article>"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        reader = PublicDocumentReader(
            client=client, resolver=lambda host: ("93.184.216.34",)
        )
        with pytest.raises(ValueError, match="scheduling"):
            await reader.read("https://publisher.example/story")
