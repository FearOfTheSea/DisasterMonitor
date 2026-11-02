"""A distinct earlier accident cannot borrow the current disaster's cause or toll."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 11, 1, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Landslide kills nine in Brookside",
    "https://daily.example/report",
    NOW,
    None,
    NOW,
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(30, NOW)
    )


def deaths(report):
    return [
        (m, c)
        for m in report.mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "earlier",
    [
        "Hace apenas dos meses, en la misma región, tuvo lugar otro accidente "
        "en una mina artesanal que dejó 13 muertos.",
        "Hace tres semanas, otro accidente dejó 13 muertos en la misma región.",
        "Hace un mes, otro accidente dejó 13 muertos en la misma región.",
        "Two months earlier, another accident in the same area killed 13 workers.",
        "Just three weeks ago, a separate accident killed 13 workers.",
    ],
)
def test_untyped_earlier_accident_cannot_become_the_current_landslide_toll(earlier):
    text = "A landslide struck Brookside and killed nine workers. " + earlier
    report = assess(text)
    assert report.article.text == text
    assert deaths(report)
    assert {claim.fact.value for _, claim in deaths(report)} == {"nine"}
    assert all(earlier not in m.text for m in report.mentions)


@pytest.mark.parametrize(
    "earlier,period",
    [
        (
            "Two months earlier, another landslide killed 13 workers in Oldtown.",
            "Two months earlier",
        ),
        (
            "Hace apenas dos meses, otro deslizamiento de tierra dejó 13 muertos "
            "en Oldtown.",
            "Hace apenas dos meses",
        ),
    ],
)
def test_explicit_earlier_hazard_keeps_its_own_historical_account(earlier, period):
    text = "A landslide struck Brookside and killed nine workers. " + earlier
    report = assess(text)
    older = [(m, c) for m, c in deaths(report) if c.fact.value == "13"]
    assert older and any(c.fact.value == "nine" for _, c in deaths(report))
    for mention, claim in older:
        assert mention.role == "historical" and "historical" in claim.qualifiers
        assert mention.time.wording == period and mention.time.start is None
        assert "nine workers" not in mention.text
    assert report.article.text == text


@pytest.mark.parametrize(
    "continuation",
    [
        "Two months ago, work began on a bridge damaged in the same landslide.",
        "Hace dos meses comenzó la reparación de la misma mina.",
        "Another worker died after the same landslide.",
    ],
)
def test_relative_time_or_another_victim_does_not_assert_a_distinct_past_disaster(
    continuation,
):
    from disaster_monitor.domain.mention_time import separate_earlier_occurrence

    accounts = separate_earlier_occurrence(continuation)
    assert len(accounts) == 1 and not accounts[0].separate


@pytest.mark.parametrize(
    "forecast",
    [
        "Two months ago, another landslide was forecast to kill 13 workers.",
        "Hace dos meses, se advirtió que otro deslizamiento podría dejar 13 muertos.",
    ],
)
def test_a_past_forecast_does_not_become_a_historical_fatal_event(forecast):
    report = assess(forecast)
    assert not any(c.fact.value == "13" for _, c in deaths(report))


def test_source_article_metadata_is_not_an_exact_clock_for_the_prior_disaster():
    text = "A landslide killed nine. Two months earlier, another landslide killed 13."
    report = assess(text)
    old = [m for m, c in deaths(report) if c.fact.value == "13"]
    assert old and all(m.time and m.time.start is None for m in old)
