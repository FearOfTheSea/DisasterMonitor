"""German flood reports keep literal hazards and their human tolls linked."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@pytest.mark.parametrize(
    "flood",
    ["Ahrtalflut", "Sturzflut", "Flutkatastrophe", "Überschwemmung", "Hochwasser"],
)
def test_german_retrospective_projects_the_fatal_flood(flood):
    title = "Klimarisiko-Index: Extremwetter in Deutschland"
    fatal_account = f"Im Juli 2021 starben bei der {flood} mehr als 180 Menschen."
    source = SourceReference(
        "news", "Daily", title, "https://daily.example/flood-report", NOW, None, NOW
    )
    report = assess_article(
        DiscoveryArticle(source, f"Der Bericht blickt zurück. {fatal_account}"),
        ReportingInterval.at_start(7, NOW),
    )
    assert report.eligibility == "eligible"
    assert any(event.disaster is Disaster.FLOOD for event in group_reports((report,)))
    claims = [
        claim
        for mention in report.mentions
        if mention.disaster is Disaster.FLOOD
        for claim in mention.claims
        if claim.fact.category == "fatalities"
    ]
    assert [(claim.fact.value, claim.excerpt) for claim in claims] == [
        ("180", fatal_account)
    ]
    assert "uncertain" in claims[0].qualifiers


def test_german_generic_flut_and_warning_compound_do_not_establish_a_flood():
    assert Disaster.FLOOD not in disasters_in_text(
        "Eine Flut von Nachrichten erreichte die Redaktion. "
        "Es besteht Hochwassergefahr."
    )
