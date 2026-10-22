"""HTTP success without publisher evidence must permit another publisher search."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
from disaster_monitor.domain.collection import CollectionPage, CollectionProviderError
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_providers import (
    PublicCollectionArticleReader,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 21, tzinfo=UTC)
LEAD = NewsFeedItem(
    "empty",
    "Daily",
    "Flood killed four in Lakeview",
    "https://daily.example/app",
    None,
    None,
    NOW,
)


class Pages:
    async def read(self, url):
        if url.endswith("/app"):
            return (
                '<html><head><title>Daily</title></head><body><div id="root"></div>'
                "<script>startApplication()</script></body></html>"
            )
        return (
            '<html><head><meta property="article:published_time" '
            'content="2026-10-20T10:00:00Z"></head><body><article>'
            "<h1>Flood killed four in Lakeview</h1>"
            "<p>Floods struck Lakeview on October 19, 2026. Four people died.</p>"
            "</article></body></html>"
        )


async def test_empty_application_shell_is_not_a_successfully_retrieved_article():
    reader = PublicCollectionArticleReader(reader=Pages())
    with pytest.raises(CollectionProviderError, match="publisher text or publication"):
        await reader.retrieve(LEAD)


async def test_publisher_publication_evidence_is_retained_without_a_full_body():
    class PublishedShell:
        async def read(self, url):
            return (
                '<html><head><meta property="article:published_time" '
                'content="2026-10-20T10:00:00Z"></head><body></body></html>'
            )

    article = await PublicCollectionArticleReader(reader=PublishedShell()).retrieve(
        LEAD
    )
    assert article.source.published_at == datetime(2026, 10, 20, 10, tzinfo=UTC)
    assert article.source.canonical_url == LEAD.canonical_url


async def test_empty_shell_retains_the_lead_and_allows_one_alternate(tmp_path):
    from dataclasses import replace

    indexed = replace(
        LEAD, search_title="La inundación deja cuatro fallecidos en Lakeview"
    )

    class Provider:
        source_id = "test-index"
        queries = ("flood",)
        supports_time_filter = True
        supports_alternates = True

        async def fetch_page(self, partition):
            if partition.alternate_for:
                assert partition.query == indexed.search_title
            return CollectionPage(
                leads=(
                    replace(indexed, canonical_url="https://daily.example/report")
                    if partition.alternate_for
                    else indexed,
                )
            )

        async def aclose(self):
            pass

    journal = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    service = ResumableDiscovery(
        (Provider(),),
        PublicCollectionArticleReader(reader=Pages()),
        journal,
        clock=lambda: NOW,
    )
    try:
        run = await service.start(7)
        await service.wait(run.scan_id)
        retained = await service.get(run.scan_id)
        reports = {r.article.source.canonical_url: r for r in retained.reports}
        snapshot = await journal.snapshot(run.scan_id, now=NOW)
        assert any(lead.canonical_url == LEAD.canonical_url for lead in snapshot.leads)
        assert any("no publisher text" in notice for notice in retained.issues)
        assert reports["https://daily.example/report"].eligibility == "eligible"
        assert reports["https://daily.example/report"].article.source.title == (
            "Flood killed four in Lakeview"
        )
        assert (
            "La inundación" not in reports["https://daily.example/report"].article.text
        )
        assert any(
            c.fact.value == "Four"
            for m in reports["https://daily.example/report"].mentions
            for c in m.claims
        )
        assert retained.collection.articles_unavailable == 1
    finally:
        await service.aclose()
