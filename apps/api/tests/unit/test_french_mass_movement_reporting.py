"""Qualified French soil/rock/waste failures retain literal human fatal reporting."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.news import NewsFeedItem

NOW = datetime(2026, 10, 30, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Local paper",
    "Local report",
    "https://local.example/report",
    NOW,
    None,
    NOW,
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )


@pytest.mark.parametrize(
    "text",
    [
        "Un éboulement de terrain a fait 3 morts.",
        "Un éboulement de terre a tué deux personnes.",
        "Un éboulement de rochers a tué trois ouvriers.",
        "Un éboulement de déchets a fait 3 morts.",
        "Un éboulement de la décharge a fait 3 morts.",
        "Un éboulement meurtrier de la falaise a enseveli des maisons.",
        "Un éboulement meurtrier d’une décharge a enseveli des maisons.",
    ],
)
def test_literal_mass_failure_exposes_attributed_death_without_an_invented_date(text):
    assert disasters_in_text(text) == (Disaster.LANDSLIDE,)
    report = assess(text)
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert report.eligibility == "eligible"
    assert claims
    assert any(c.fact.value not in ("0", "Unknown") for c in claims)
    assert all(c.fact.source == SOURCE for c in claims)
    assert all(m.time is None for m in report.mentions)
    assert report.article.text == text


@pytest.mark.parametrize(
    "text",
    [
        "Un éboulement de terrain n’a fait aucun mort.",
        "Un éboulement de rochers pourrait faire 3 morts.",
        "Un exercice simule un éboulement meurtrier de la falaise.",
        "Un éboulement de terrain a tué deux vaches.",
    ],
)
def test_zero_forecast_drill_and_nonhuman_loss_do_not_assert_human_deaths(text):
    assert disasters_in_text(text) == (Disaster.LANDSLIDE,)
    report = assess(text)
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert not any(c.fact.value not in ("0", "Unknown") for c in claims)


@pytest.mark.parametrize(
    "text",
    [
        "Un éboulement d’un bâtiment a fait 3 morts.",
        "Un éboulement d’une façade a tué deux personnes.",
        "Un éboulement électoral menace le parti.",
        "Un éboulement de messages envahit les réseaux.",
    ],
)
def test_structural_and_figurative_failures_are_not_silently_called_ground_slides(text):
    assert Disaster.LANDSLIDE not in disasters_in_text(text)


def test_fatal_adjective_can_prioritize_inspection_without_a_numeric_toll():
    lead = NewsFeedItem(
        "local",
        "Local paper",
        "Un éboulement meurtrier de la falaise",
        "https://local.example/report",
        None,
        None,
    )
    assert lead_retrieval_priority(lead) == 3


def test_primary_and_earlier_flood_context_keep_fatalities_with_the_mass_failure():
    text = (
        "Un éboulement de la décharge a fait 3 morts.\n"
        "Les survivants ont reçu une aide.\n"
        "Une année auparavant, des inondations avaient endommagé des logements."
    )
    report = assess(text)
    slide = [m for m in report.mentions if m.disaster == Disaster.LANDSLIDE]
    assert any(
        c.fact.category == "fatalities" and c.fact.value == "3"
        for m in slide
        for c in m.claims
    )
    assert not any(
        c.fact.category == "fatalities" and c.fact.value not in ("0", "Unknown")
        for m in report.mentions
        if m.disaster == Disaster.FLOOD
        for c in m.claims
    )


@pytest.mark.parametrize(
    "text",
    [
        "Un éboulement meurtrier de la falaise a été évité.",
        "Le risque d’un éboulement meurtrier de la falaise inquiète les habitants.",
        "Trois meurtriers ont observé un éboulement de terrain.",
    ],
)
def test_avoided_risk_and_people_described_as_killers_are_not_actual_casualties(text):
    report = assess(text)
    assert not any(
        c.fact.category == "fatalities" and c.fact.value not in ("0", "Unknown")
        for m in report.mentions
        for c in m.claims
    )


def test_multiple_fatal_mass_failures_do_not_become_a_two_death_toll():
    report = assess("Deux éboulements meurtriers de terrain ont été signalés.")
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert claims
    assert all(
        c.fact.value == "Unknown" and "scope unresolved" in c.qualifiers for c in claims
    )


def test_a_fatal_modifier_does_not_turn_a_neighboring_flood_into_a_fatal_flood():
    text = (
        "Un éboulement meurtrier de la falaise a endommagé une route, "
        "et des inondations ont touché le village voisin."
    )
    report = assess(text)
    assert any(
        c.fact.category == "fatalities" and c.fact.value not in ("0", "Unknown")
        for m in report.mentions
        if m.disaster == Disaster.LANDSLIDE
        for c in m.claims
    )
    assert not any(
        c.fact.category == "fatalities" and c.fact.value not in ("0", "Unknown")
        for m in report.mentions
        if m.disaster == Disaster.FLOOD
        for c in m.claims
    )


@pytest.mark.parametrize(
    "text",
    [
        "Un éboulement meurtrier de terrain n’a pas eu lieu.",
        "Un éboulement meurtrier de la falaise est fictif.",
    ],
)
def test_an_explicit_nonoccurrence_or_fiction_is_not_a_reported_human_death(text):
    assert not any(
        c.fact.category == "fatalities" and c.fact.value not in ("0", "Unknown")
        for m in assess(text).mentions
        for c in m.claims
    )


def test_a_coordinated_joint_subject_does_not_allocate_its_deaths_to_each_hazard():
    text = "Un éboulement meurtrier de la falaise, et des inondations ont fait 5 morts."
    report = assess(text)
    assert not any(
        c.fact.category == "fatalities" and c.fact.value == "5"
        for m in report.mentions
        for c in m.claims
    )
