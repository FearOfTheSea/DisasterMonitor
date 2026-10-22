"""Explicit eruption verbs must not turn historical eruption deaths into fire deaths."""

from dataclasses import replace
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

NOW = datetime(2026, 10, 21, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Park wildfire update",
    "https://daily.example/fire",
    NOW,
    None,
    NOW,
)


def test_named_mount_eruption_keeps_its_fatalities_separate_from_the_current_wildfire():
    report = assess_article(
        DiscoveryArticle(
            SOURCE,
            "A wildfire in Green National Park killed four people on October 15. "
            "The park is an active volcanic complex. "
            "In December 2021, at least 51 people were killed "
            "when Mount Ashvale erupted.",
        ),
        ReportingInterval.at_start(7, NOW),
    )
    eruption = [m for m in report.mentions if m.disaster is Disaster.VOLCANIC_ERUPTION]
    assert eruption
    assert eruption[0].role == "historical"
    assert eruption[0].time is not None
    assert eruption[0].time.start == datetime(2021, 12, 1, tzinfo=UTC)
    assert eruption[0].time.end == datetime(2022, 1, 1, tzinfo=UTC)
    assert eruption[0].time.precision == "range"
    assert any(
        c.fact.category == "fatalities" and c.fact.value == "51"
        for m in eruption
        for c in m.claims
    )
    assert not any(
        c.fact.category == "fatalities" and c.fact.value == "51"
        for m in report.mentions
        if m.disaster is Disaster.WILDFIRE
        for c in m.claims
    )


@pytest.mark.parametrize(
    "text",
    [
        "The volcano last erupted in 2021.",
        "Mount Ashvale has erupted.",
        "Mt. Ashvale is erupting.",
    ],
)
def test_explicit_volcano_and_named_mount_verb_forms_are_hazard_language(text):
    assert disasters_in_text(text) == (Disaster.VOLCANIC_ERUPTION,)


@pytest.mark.parametrize(
    "text",
    [
        "Violence erupted after the flood.",
        "A political row erupts over landslide response.",
    ],
)
def test_figurative_eruption_verbs_do_not_create_a_volcanic_hazard(text):
    assert Disaster.VOLCANIC_ERUPTION not in disasters_in_text(text)


def test_historical_famine_casualties_are_not_assigned_to_looming_floods():
    text = (
        "Floods in 2023 killed 188 people. The looming floods risk deepening "
        "a hunger crisis in a country still "
        "haunted by the famine of 2011, which claimed the lives of an estimated "
        "250,000 people, many of them children."
    )
    report = assess_article(
        DiscoveryArticle(replace(SOURCE, title="Floods and hunger crisis"), text),
        ReportingInterval.at_start(7, NOW),
    )
    assert report.mentions
    assert any(c.fact.value == "188" for m in report.mentions for c in m.claims)
    assert not any("famine" in c.excerpt for m in report.mentions for c in m.claims)
    assert any("250,000" in m.text for m in report.mentions)
