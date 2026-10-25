"""A hypothetical population-adjusted equivalent is not an observed death toll."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Drought history", "https://daily.example/report", NOW, None, NOW
)


def fatalities(text):
    return [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "comparison",
    [
        "That would be comparable to about 249 million deaths "
        "based on today’s population.",
        "It would be equivalent to 40 million deaths today.",
        "That would be comparable to 40 million fatalities in the current population.",
    ],
)
def test_population_adjusted_equivalents_do_not_become_actual_fatalities(comparison):
    assert not fatalities(comparison)
    report = assess_article(
        DiscoveryArticle(SOURCE, "A drought was described. " + comparison),
        ReportingInterval.at_start(1, NOW),
    )
    assert not report.fatality_evidence
    assert all(
        not [c for c in m.claims if c.fact.category == "fatalities"]
        for m in report.mentions
    )


def test_historical_observed_toll_remains_with_its_original_wording():
    actual = "During the historical drought, an estimated 50 million people died."
    text = (
        actual + " That would be comparable to about 249 million deaths "
        "based on today’s population."
    )
    (claim,) = fatalities(text)
    assert claim.fact.value == "50 million"
    assert claim.excerpt == actual


@pytest.mark.parametrize(
    "text",
    [
        "Fifty people died in the flood, a toll comparable to last year’s 50 deaths.",
        "The flood killed five people; the winds would be comparable to a hurricane.",
        "Two people died today in the drought.",
    ],
)
def test_actual_comparative_or_present_day_reporting_remains_visible(text):
    assert fatalities(text)
