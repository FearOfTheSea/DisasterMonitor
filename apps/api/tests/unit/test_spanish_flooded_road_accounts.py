"""Flooded-road reporting requires explicit water and attributed human deaths."""

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
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 24, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Regional report", "https://daily.example/report", NOW, None, NOW
)


@pytest.mark.parametrize("wording", ["perdió la vida", "perdiendo la vida"])
def test_explicit_flooded_road_and_death_idiom_retain_unknown_count(wording):
    text = (
        "El hombre intentó cruzar por un camino inundado, "
        f"{wording} al ser arrastrado por la corriente de agua."
    )
    assert disasters_in_text(text) == (Disaster.FLOOD,)
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.eligibility == "eligible"
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert len(claims) == 1
    assert claims[0].fact.value == "Reported; count unknown"
    assert claims[0].excerpt == text
    assert claims[0].fact.source == SOURCE
    assert all(m.time is None for m in report.mentions)


@pytest.mark.parametrize(
    "text",
    [
        "Un hombre perdió la vida por las intensas lluvias.",
        "El periodista quedó inundado de mensajes sobre un hombre que murió.",
    ],
)
def test_rain_or_a_metaphorical_inundation_is_not_an_explicit_flood(text):
    assert Disaster.FLOOD not in disasters_in_text(text)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Dos personas perdieron la vida en una carretera inundada.", "2"),
        ("El hombre no perdió la vida al cruzar el camino inundado.", "0"),
        ("Nadie perdió la vida en la calle inundada.", "0"),
    ],
)
def test_death_idiom_preserves_explicit_count_and_denials(text, value):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == value
    assert claim.excerpt == text


@pytest.mark.parametrize(
    "text",
    [
        "Las baterías perdieron la vida útil en la calle inundada.",
        "Dos vacas perdieron la vida en la carretera inundada.",
    ],
)
def test_equipment_life_and_animal_losses_are_not_human_deaths(text):
    assert not extract_reported_impacts(text, SOURCE)


def test_predicted_flooded_road_toll_is_not_observed_reporting():
    text = "Se prevén caminos inundados donde podrían perder la vida dos personas."
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions and all(m.role == "forecast" for m in report.mentions)
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )
