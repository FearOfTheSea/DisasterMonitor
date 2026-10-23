"""Joined floodwater wording must keep local fatal accounts inspectable."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Regional update", "https://news.example/report", NOW, None, NOW
)


@pytest.mark.parametrize("water", ["floodwater", "floodwaters"])
def test_local_floodwater_death_is_retained_without_treating_age_as_a_toll(water):
    text = (
        f"A 62-year-old man has died after his car was swept onto a beach by {water}."
    )
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )
    assert report.eligibility == "eligible"
    assert report.fatality_evidence == (text,)
    (mention,) = report.mentions
    assert mention.disaster is Disaster.FLOOD
    assert mention.role == "reported"
    assert text in mention.text
    assert all(c.fact.value != "62" for c in mention.claims)


def test_floodwater_forecast_does_not_establish_actual_fatalities():
    report = assess_article(
        DiscoveryArticle(SOURCE, "Forecast: floodwaters could kill two people."),
        ReportingInterval.at_start(1, NOW),
    )
    assert report.mentions
    assert all(m.role == "forecast" and not m.claims for m in report.mentions)
    assert not report.fatality_evidence


def test_rescue_from_floodwaters_is_not_a_fatality_account():
    report = assess_article(
        DiscoveryArticle(SOURCE, "Two people were rescued from floodwaters."),
        ReportingInterval.at_start(1, NOW),
    )
    assert report.mentions
    assert not report.fatality_evidence
    assert all(
        c.fact.category != "fatalities" for m in report.mentions for c in m.claims
    )


def test_a_product_word_containing_floodwater_is_not_a_hazard_mention():
    assert not disasters_in_text("New floodwaterproof boots are on sale")
