"""Literal flood wording must participate in casualty and comparison scope."""

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

NOW = datetime(2026, 10, 25, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Informe regional", "https://daily.example/report", NOW, None, NOW
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )


@pytest.mark.parametrize(
    "wording", ["La riada dejó", "Las riadas dejaron", "LA RIADA DEJÓ"]
)
def test_fatal_flood_accounts_are_accessible_without_an_inundacion_synonym(wording):
    text = f"{wording} dos muertos en el pueblo."
    assert disasters_in_text(text) == (Disaster.FLOOD,)
    report = assess(text)
    assert report.eligibility == "eligible"
    assert report.article.text == text
    fatalities = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert len(fatalities) == 1
    assert fatalities[0].fact.value == "2"
    assert fatalities[0].excerpt == text
    assert fatalities[0].fact.source == SOURCE


def test_a_comparison_cannot_allocate_the_flood_toll_to_the_landslide():
    text = (
        "El reciente deslave se debió al colapso de un glaciar, por causas "
        "similares a las de la riada que dejó más de 1 400 muertos en agosto."
    )
    report = assess(text)
    assert {m.disaster for m in report.mentions} == {
        Disaster.FLOOD,
        Disaster.LANDSLIDE,
    }
    assert report.article.text == text
    assert all(text in m.excerpt for m in report.mentions)
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )
    assert all(any("Combined" in n for n in m.notices) for m in report.mentions)


def test_distinct_sentences_retain_their_own_flood_and_landslide_counts():
    report = assess("La riada dejó dos muertos. Un deslave dejó tres muertos.")
    assert {
        (m.disaster, c.fact.value)
        for m in report.mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    } == {(Disaster.FLOOD, "2"), (Disaster.LANDSLIDE, "3")}


@pytest.mark.parametrize(
    "subject", ["mensajes", "homenajes", "críticas", "solicitudes"]
)
def test_a_figurative_riada_does_not_supply_a_physical_hazard(subject):
    text = f"Una riada de {subject} siguió a la muerte del actor."
    assert disasters_in_text(text) == ()
    assert assess(text).eligibility == "unclassified"


def test_a_real_flood_survives_a_separate_figurative_phrase():
    text = "Una riada dejó dos muertos; llegó una riada de mensajes de condolencia."
    assert disasters_in_text(text) == (Disaster.FLOOD,)
    assert any(
        c.fact.value == "2"
        for m in assess(text).mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    )
