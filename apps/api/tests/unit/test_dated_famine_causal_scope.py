"""A dated famine is not automatically a death toll for the current hazard."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Drought report", "https://daily.example/report", NOW, None, NOW
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )


def fatalities(report):
    return [
        claim
        for mention in report.mentions
        if mention.disaster is Disaster.DROUGHT
        for claim in mention.claims
        if claim.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "background",
    [
        "the 1984 famine that killed hundreds of thousands of people",
        "the famine of 1984 that killed hundreds of thousands of people",
        "the famine in 1984 that killed hundreds of thousands of people",
        "the 1991 famine that killed thousands of people",
    ],
)
def test_historical_famine_tolls_remain_context_without_a_drought_link(background):
    text = (
        "The drought leaves little respite for a nation with a history of crises, "
        f"including {background} across the region."
    )
    report = assess(text)
    assert report.article.text == text
    assert any("famine" in mention.text for mention in report.mentions)
    assert not fatalities(report)
    assert not report.fatality_evidence


@pytest.mark.parametrize(
    "text",
    [
        "Drought caused the 1984 famine that killed thousands of people.",
        "Drought triggered the famine of 1984 that killed thousands of people.",
        "Drought led to the famine in 1984 that killed thousands of people.",
        "The drought-induced 1984 famine killed thousands of people.",
        "The 1984 famine caused by drought killed thousands of people.",
        "The famine of 1984 was caused by drought and killed thousands of people.",
    ],
)
def test_explicit_drought_attribution_preserves_the_actual_famine_toll(text):
    report = assess(text)
    assert fatalities(report)
    assert any(c.fact.value == "thousands" for c in fatalities(report))
    assert report.fatality_evidence


def test_a_causal_link_to_another_famine_does_not_explain_the_dated_famine_toll():
    text = (
        "Drought caused a famine this year, while the 1984 famine "
        "killed hundreds of thousands of people."
    )
    report = assess(text)
    assert not fatalities(report)
    assert report.article.text == text


def test_a_separate_actual_current_drought_toll_is_not_removed():
    text = (
        "The drought killed two people. The nation recalls the 1984 famine "
        "that killed hundreds of thousands of people."
    )
    claims = fatalities(assess(text))
    assert claims
    assert all(c.fact.value == "two" for c in claims)


def test_other_competing_causes_still_prevent_a_combined_toll_allocation():
    report = assess(
        "Conflict and drought caused the famine of 1984 that killed thousands."
    )
    assert not fatalities(report)
