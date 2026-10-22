"""A successful damage report does not settle an index's unverified fatality hint."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
from disaster_monitor.domain.collection import CollectionPage
from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 22, tzinfo=UTC)
LEAD = NewsFeedItem(
    "index-lead",
    "Daily",
    "Damage bulletin",
    "https://daily.example/damage",
    None,
    None,
    discovery_hint="An earthquake killed one person in Lakeview.",
)


def article(url, text):
    return DiscoveryArticle(
        SourceReference(
            "news", "Daily", "Local earthquake report", url, NOW, None, NOW
        ),
        text,
    )


@pytest.mark.parametrize("alternate_reports_fatality", [True, False])
async def test_retains_successful_damage_report_and_seeks_at_most_one_alternate(
    tmp_path, alternate_reports_fatality
):
    queries = []
    retrieved = []

    class Provider:
        source_id = "test-index"
        queries = ("earthquake",)
        supports_time_filter = False
        supports_alternates = True

        async def fetch_page(self, part):
            queries.append(part)
            return CollectionPage(
                leads=(
                    replace(LEAD, canonical_url="https://other.example/report")
                    if part.alternate_for
                    else LEAD,
                )
            )

    primary = article(
        LEAD.canonical_url, "An earthquake struck Lakeview. Fifteen homes were damaged."
    )
    secondary = article(
        "https://other.example/report",
        "One person died after the earthquake struck Lakeview."
        if alternate_reports_fatality
        else "An earthquake struck Lakeview. A bridge was damaged.",
    )

    class Reader:
        async def retrieve(self, lead):
            retrieved.append(lead.canonical_url)
            return primary if lead.canonical_url == LEAD.canonical_url else secondary

    journal = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    service = ResumableDiscovery((Provider(),), Reader(), journal, clock=lambda: NOW)
    try:
        run = await service.start(7)
        await service.wait(run.scan_id)
        retained = await service.get(run.scan_id)
        reports = {x.article.source.canonical_url: x for x in retained.reports}
        assert set(reports) == {LEAD.canonical_url, secondary.source.canonical_url}
        assert reports[LEAD.canonical_url].article.text == primary.text
        assert not any(
            c.fact.category == "fatalities"
            for m in reports[LEAD.canonical_url].mentions
            for c in m.claims
        )
        if alternate_reports_fatality:
            assert any(
                c.fact.category == "fatalities" and c.fact.value == "One"
                for m in reports[secondary.source.canonical_url].mentions
                for c in m.claims
            )
        assert len([x for x in queries if x.alternate_for]) == 1
        assert (
            next(x for x in queries if x.alternate_for).alternate_for
            == LEAD.canonical_url
        )
        assert len(retrieved) == 2
        assert retained.collection.articles_retrieved == 2
        assert retained.collection.articles_unavailable == 0
    finally:
        await service.aclose()


@pytest.mark.parametrize(
    ("hint", "text"),
    [
        (
            "An earthquake damaged homes.",
            "An earthquake struck Lakeview. Fifteen homes were damaged.",
        ),
        (
            "An earthquake killed one person.",
            "One person died after the earthquake struck Lakeview.",
        ),
        ("An earthquake killed one person.", "El terremoto dejó dos personas muertas."),
        ("An earthquake killed one person.", "Gempa menewaskan satu orang."),
    ],
)
async def test_no_followup_when_hint_absent_or_publisher_reports_fatalities(
    tmp_path, hint, text
):
    queries = []

    class Provider:
        source_id = "test-index"
        queries = ("earthquake",)
        supports_time_filter = False
        supports_alternates = True

        async def fetch_page(self, part):
            queries.append(part)
            return CollectionPage(leads=(replace(LEAD, discovery_hint=hint),))

    class Reader:
        async def retrieve(self, lead):
            return article(lead.canonical_url, text)

    journal = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    service = ResumableDiscovery((Provider(),), Reader(), journal, clock=lambda: NOW)
    try:
        run = await service.start(7)
        await service.wait(run.scan_id)
        retained = await service.get(run.scan_id)
        assert len(queries) == 1
        assert retained.collection.articles_retrieved == 1
    finally:
        await service.aclose()
