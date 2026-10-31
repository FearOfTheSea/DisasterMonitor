"""Weather summaries retain source context without transferring another cause's toll."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 9, 15, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Regional Daily",
    "Weather report",
    "https://daily.example/weather",
    NOW,
    None,
    NOW,
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )


def fatality_claims(report, hazard):
    return [
        c
        for m in report.mentions
        if m.disaster is hazard
        for c in m.claims
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Seven lightning deaths, landslides and crop damage reported.",
        "Seven people died in rain-related incidents while landslides damaged roads.",
        "Lightning and landslides killed seven people.",
        "Landslides and lightning killed seven people.",
        "Two people were killed by lightning as floodwaters damaged houses.",
        "Lightning strikes claimed seven lives and sixty landslides blocked roads. "
        "The reported fatalities, landslides and crop damage disrupted travel.",
    ],
)
def test_a_competing_or_unallocated_weather_account_is_not_a_supported_hazard_toll(
    text,
):
    report = assess(text)
    assert report.article.text == text and report.mentions
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )
    assert not report.fatality_evidence


@pytest.mark.parametrize(
    "text,hazard",
    [
        (
            "Lightning killed seven people and a landslide killed two workers.",
            Disaster.LANDSLIDE,
        ),
        (
            "A landslide killed two workers while lightning killed seven people.",
            Disaster.LANDSLIDE,
        ),
        ("Flooding killed two people while lightning killed seven.", Disaster.FLOOD),
        (
            "Lightning destroyed a transformer while a landslide killed two people.",
            Disaster.LANDSLIDE,
        ),
        ("Lightning sparked a wildfire that killed two people.", Disaster.WILDFIRE),
        (
            "Lightning struck and triggered a wildfire that killed two people.",
            Disaster.WILDFIRE,
        ),
        (
            "Lightning killed seven people. A landslide killed two workers.",
            Disaster.LANDSLIDE,
        ),
    ],
)
def test_an_explicit_hazard_death_account_survives_the_other_weather_context(
    text, hazard
):
    report = assess(text)
    assert report.article.text == text
    claims = fatality_claims(report, hazard)
    assert claims and {c.fact.value for c in claims} == {"two"}
    assert report.fatality_evidence


def test_an_explicit_subset_uses_its_own_count_without_allocating_the_regional_total():
    text = "Seven people died in rain-related incidents, including two in a landslide."
    report = assess(text)
    assert report.article.text == text
    claims = fatality_claims(report, Disaster.LANDSLIDE)
    assert claims and {c.fact.value for c in claims} == {"two"}
    assert all(c.excerpt == text for c in claims)


@pytest.mark.parametrize(
    "text",
    [
        "No deaths were reported in rain-related incidents, "
        "including two in a landslide.",
        "Seven sheep died in weather-related incidents, including two in a landslide.",
    ],
)
def test_a_subset_does_not_override_an_explicit_zero_or_invent_human_deaths(text):
    report = assess(text)
    assert report.article.text == text
    assert not any(
        c.fact.value not in ("0", "Unknown")
        for c in fatality_claims(report, Disaster.LANDSLIDE)
    )
    assert not report.fatality_evidence
