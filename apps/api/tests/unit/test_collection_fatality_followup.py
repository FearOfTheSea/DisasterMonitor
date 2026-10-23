"""Discovery hints can request more wording; they cannot establish a casualty claim."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.collection import fatality_hint_needs_followup
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem

NOW = datetime(2026, 10, 22, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Earthquake report", "https://daily.example/story", NOW, None, NOW
)
LEAD = NewsFeedItem(
    "lead",
    "Daily",
    "Earthquake report",
    SOURCE.canonical_url,
    None,
    None,
    discovery_hint="An earthquake killed one person.",
)


@pytest.mark.parametrize(
    ("text", "needed"),
    [
        ("An earthquake struck Lakeview. Fifteen homes were damaged.", True),
        ("One person died after the earthquake struck Lakeview.", False),
        ("No deaths were reported after the earthquake.", True),
        ("The death toll after the earthquake is unknown.", True),
        ("Forecast: an earthquake could leave four people dead.", True),
        ("Three cows died after the earthquake.", True),
        ("El terremoto dejó dos personas muertas.", False),
        ("Les séismes ont fait deux morts.", False),
        ("Gempa menewaskan satu orang.", False),
    ],
)
def test_followup_uses_publisher_accounts_not_the_index_hint(text, needed):
    article = DiscoveryArticle(SOURCE, text)
    assert fatality_hint_needs_followup(LEAD, article) is needed
    assert article.text == text


def test_missing_only_index_lead_does_not_request_a_fatality_followup():
    lead = replace(
        LEAD, discovery_hint="Four people remain missing after the earthquake."
    )
    assert not fatality_hint_needs_followup(
        lead, DiscoveryArticle(SOURCE, "An earthquake struck Lakeview.")
    )


def test_deadly_index_wording_requests_reporting_without_creating_a_claim():
    lead = replace(
        LEAD, title="Deadly earthquake response reviewed", discovery_hint=None
    )
    article = DiscoveryArticle(SOURCE, "An earthquake struck Lakeview.")
    assert fatality_hint_needs_followup(lead, article)
    assert not assess_article(
        article, ReportingInterval.at_start(1, NOW)
    ).fatality_evidence
