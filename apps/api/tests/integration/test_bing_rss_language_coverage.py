"""Generic hazard queries cover the evaluation languages without event inputs."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from disaster_monitor.domain.collection import CollectionPartition
from disaster_monitor.infrastructure.news.bing_collection import (
    BingRssCollectionProvider,
)

NOW = datetime(2026, 10, 25, tzinfo=UTC)
LANGUAGES = (
    (
        "de-DE",
        (
            "Erdbeben",
            "Hochwasser",
            "Waldbrand",
            "Erdrutsch",
            "Wirbelsturm",
            "Vulkanausbruch",
            "Dürre",
        ),
        ("Tote", "starben"),
    ),
    (
        "tr-TR",
        (
            "deprem",
            "sel",
            "orman yangını",
            "heyelan",
            "kasırga",
            "volkanik patlama",
            "kuraklık",
        ),
        ("öldü", '"hayatını kaybetti"'),
    ),
    (
        "ar-SA",
        (
            "زلزال",
            "فيضانات",
            "حرائق الغابات",
            "انهيار أرضي",
            "إعصار",
            "ثوران بركاني",
            "جفاف",
        ),
        ("قتلى", "وفيات"),
    ),
)
CASES = [
    (f'"{hazard}" {death_word}', market)
    for market, hazards, death_words in LANGUAGES
    for hazard in hazards
    for death_word in death_words
]


@pytest.mark.parametrize(("query", "market"), CASES)
async def test_configured_language_seed_retains_us_and_native_pages(query, market):
    assert query in BingRssCollectionProvider.queries
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=b"<rss><channel/></rss>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = BingRssCollectionProvider(client=client, minimum_interval=0)
        cursor = ""
        for expected in ("native-first-relevance", "us-recent", "us-relevance", None):
            page = await provider.fetch_page(
                CollectionPartition(
                    provider.source_id,
                    query,
                    NOW - timedelta(hours=6),
                    NOW,
                    cursor=cursor,
                )
            )
            assert page.next_cursor == expected
            assert not page.articles
            cursor = page.next_cursor
    assert [r.url.params["mkt"] for r in calls] == [market, market, "en-US", "en-US"]
    assert all(r.url.params["q"] == query for r in calls)


def test_language_families_add_bounded_generic_queries_without_duplicates():
    assert len(CASES) == 42
    assert len(set(BingRssCollectionProvider.queries)) == 113
    # Existing English, Spanish, French, Indonesian and Portuguese routes remain.
    for query in (
        '"earthquake"',
        '"volcanic eruption" deaths',
        '"inundaciones" muertos',
        '"glissement de terrain" morts',
        '"gempa" meninggal',
        '"enchente" mortos',
    ):
        assert query in BingRssCollectionProvider.queries
