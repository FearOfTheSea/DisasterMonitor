"""Recalling another disaster does not transfer the preceding death account."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 25, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Disaster recovery report",
    "https://daily.example/report",
    NOW,
    None,
    NOW,
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )


def tolls(report, hazard):
    return [
        c
        for m in report.mentions
        if m.disaster is hazard
        for c in m.claims
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "reference",
    [
        "y que me acuerde de los deslaves ocurridos en 1999",
        "y que se acuerden de los deslaves ocurridos en 1999",
        "lo que me recuerda a los deslaves ocurridos en 1999",
        "y esto nos recuerda a los deslaves ocurridos en 1999",
    ],
)
def test_a_prior_death_statement_is_not_a_toll_for_the_recalled_hazard(reference):
    text = f"Me dijeron que son muchos fallecidos {reference}."
    report = assess(text)
    assert report.article.text == text
    assert any(reference in m.excerpt for m in report.mentions)
    assert not tolls(report, Disaster.LANDSLIDE)
    assert not report.fatality_evidence


@pytest.mark.parametrize(
    "reference",
    [
        "which reminded her of the landslide in 1999",
        "which reminds them of the landslide in 1999",
        "and this reminded us of the landslide in 1999",
    ],
)
def test_english_recollection_does_not_attribute_earlier_deaths(reference):
    text = f"There were many deaths, {reference}."
    report = assess(text)
    assert not tolls(report, Disaster.LANDSLIDE)
    assert report.article.text == text


@pytest.mark.parametrize(
    "text,value",
    [
        ("Recuerda los deslaves que mataron a tres personas.", "3"),
        (
            "Son muchos fallecidos y que me acuerde de los deslaves "
            "que mataron a tres personas en 1999.",
            "3",
        ),
        (
            "There were many injuries, which reminded her of the landslide "
            "that killed five people in 1999.",
            "five",
        ),
        ("The landslide killed two people, which reminded her of a long wait.", "two"),
    ],
)
def test_actual_deaths_in_the_hazard_own_account_remain_reported(text, value):
    claims = tolls(assess(text), Disaster.LANDSLIDE)
    assert claims
    assert all(c.fact.value == value for c in claims)


def test_separate_current_toll_and_actual_historical_toll_remain_distinct():
    text = (
        "El terremoto mató a cinco personas. Me dijeron que son muchos fallecidos "
        "y que me acuerde de los deslaves ocurridos en 1999. "
        "Los deslaves mataron a tres personas."
    )
    report = assess(text)
    assert any(c.fact.value == "5" for c in tolls(report, Disaster.EARTHQUAKE))
    assert [c.fact.value for c in tolls(report, Disaster.LANDSLIDE)] == ["3"]
    assert report.article.text == text


def test_recalling_the_same_hazard_does_not_combine_two_occurrence_tolls():
    text = (
        "The landslide killed two people, which reminded her of the landslide "
        "that killed five people in 1999."
    )
    report = assess(text)
    claims = tolls(report, Disaster.LANDSLIDE)
    assert claims
    assert all(c.fact.value == "Unknown" for c in claims)
    assert all("scope unresolved" in c.qualifiers for c in claims)
    assert report.article.text == text
