"""Literal regional reporting remains attributed, bounded, and inspectable."""

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
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 22, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Regional News",
    "Regional bulletin",
    "https://regional.example/story",
    NOW,
    None,
    NOW,
)


@pytest.mark.parametrize(
    ("text", "hazard", "value"),
    [
        ("Banjir menewaskan dua orang.", Disaster.FLOOD, "2"),
        ("Tiga pekerja tewas akibat tanah longsor.", Disaster.LANDSLIDE, "3"),
        ("Uma pessoa morreu após um deslizamento de terra.", Disaster.LANDSLIDE, "1"),
        (
            "Dois trabalhadores morreram após deslizamento de solo.",
            Disaster.LANDSLIDE,
            "2",
        ),
        ("Enchentes deixaram três pessoas mortas.", Disaster.FLOOD, "3"),
        ("Enxurrada matou duas pessoas.", Disaster.FLOOD, "2"),
        ("Enxurrada mata duas pessoas.", Disaster.FLOOD, "2"),
        ("Duas pessoas morrem após deslizamento de terra.", Disaster.LANDSLIDE, "2"),
        (
            "Maria Lima perdeu a vida após um deslizamento de terra.",
            Disaster.LANDSLIDE,
            "Reported; count unknown",
        ),
        ("Duas pessoas perderam a vida na enchente.", Disaster.FLOOD, "2"),
        ("Inundações causaram quatro mortes.", Disaster.FLOOD, "4"),
        ("A inundação causou a morte de duas pessoas.", Disaster.FLOOD, "2"),
        ("A woman died in a rockfall.", Disaster.LANDSLIDE, "Reported; count unknown"),
        ("A veld fire killed two people.", Disaster.WILDFIRE, "two"),
    ],
)
def test_literal_hazard_and_fatal_accounts_retain_source_without_invented_onset(
    text, hazard, value
):
    assert disasters_in_text(text) == (hazard,)
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.eligibility == "eligible"
    assert report.mentions
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert any(c.fact.value == value and c.excerpt == text for c in claims)
    assert all(c.fact.source == SOURCE for c in claims)
    assert all(m.time is None for m in report.mentions)
    assert report.article.text == text


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Não houve mortos nas enchentes.", "0"),
        ("Nenhuma pessoa morreu no deslizamento.", "0"),
        ("Ninguém morreu no deslizamento.", "0"),
        ("Não morreu ninguém na enchente.", "0"),
        ("Ninguém perdeu a vida na enchente.", "0"),
        ("Não perdeu a vida na enchente.", "0"),
        ("Não há relatos de mortos nas enchentes.", "Unknown"),
        ("Duas pessoas mortas ou desaparecidas após a enxurrada.", "Unknown"),
        ("Um homem de 47 anos morreu após o deslizamento.", "Reported; count unknown"),
        ("Enchentes mataram pelo menos duas pessoas.", "2"),
        ("Deux personnes sont mortes dans les inondations.", "2"),
        ("Duas pessoas morreram nas enchentes.", "2"),
        ("Enchente matou cinco pessoas e animais.", "Unknown"),
    ],
)
def test_zero_unknown_age_minimum_and_overlapping_language_terms_remain_distinct(
    text, value
):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == value
    assert claim.excerpt == text
    if "pelo menos" in text:
        assert "uncertain" in claim.qualifiers
    if "animais" in text:
        assert "scope unresolved" in claim.qualifiers


@pytest.mark.parametrize(
    "text",
    [
        "Banjir diprediksi menewaskan tiga orang.",
        "Longsor berpotensi menewaskan dua orang.",
        "Enchentes poderiam matar três pessoas.",
        "Simulação de deslizamento deixou duas pessoas mortas.",
    ],
)
def test_forecast_and_drill_do_not_claim_an_observed_human_toll(text):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions and all(m.role == "forecast" for m in report.mentions)
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


@pytest.mark.parametrize(
    "text",
    [
        "Banjir menewaskan tiga sapi.",
        "Enchente matou cinco vacas.",
        "Enchente deixou cinco animais mortos.",
        "Enchente mata duas árvores.",
        "Duas árvores perderam a vida na enchente.",
        "Três árvores morreram durante a enchente.",
    ],
)
def test_explicit_nonhuman_losses_do_not_become_human_fatalities(text):
    assert not extract_reported_impacts(text, SOURCE)


@pytest.mark.parametrize(
    "text",
    [
        "A roof collapsed, killing two workers.",
        "A building collapsed, killing two people.",
        "A coal mine explosion killed three miners.",
        "Um prédio desmoronou e dois trabalhadores morreram.",
    ],
)
def test_unrelated_structural_failures_are_not_classified_as_land_movement(text):
    assert Disaster.LANDSLIDE not in disasters_in_text(text)


def test_native_fatal_headline_is_only_a_retrieval_priority_hint():
    lead = NewsFeedItem(
        "lead",
        "Regional",
        "Deslizamento matou duas pessoas",
        SOURCE.canonical_url,
        None,
        None,
        NOW,
    )
    assert lead_retrieval_priority(lead) == 1
    assert lead.published_at is None


def test_competing_armed_cause_is_not_assigned_to_the_flood():
    text = "Enchente atingiu o bairro, mas um tiroteio matou duas pessoas."
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


def test_annual_rain_toll_is_not_allocated_to_a_local_slide():
    text = (
        "## Uma mulher morreu após um deslizamento de terra\n"
        "O estado registrou 21 mortes provocadas pelas chuvas desde o início do ano. "
        "Uma mulher de 47 anos morreu após um deslizamento de terra atingir sua casa."
    )
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert claims
    assert all(c.fact.value != "21" for c in claims)
    assert any("47 anos" in c.excerpt for c in claims)
    assert report.article.text == text


@pytest.mark.parametrize(
    "text",
    [
        "O deslizamento de terra provocado pelas chuvas matou duas pessoas.",
        "A enchente causada pelas chuvas matou duas pessoas.",
    ],
)
def test_direct_hazard_death_account_survives_its_reported_rain_cause(text):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert any(c.fact.value == "2" for m in report.mentions for c in m.claims)


@pytest.mark.parametrize(
    ("text", "hazard"),
    [
        ("Um jovem morreu após um desmoronamento de terra.", Disaster.LANDSLIDE),
        (
            "Tebing tanah longsor dan menimbun tiga pekerja. Dua pekerja tewas.",
            Disaster.LANDSLIDE,
        ),
    ],
)
def test_explicit_soil_failure_and_burial_are_reported_occurrences(text, hazard):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert any(m.disaster == hazard and m.role == "reported" for m in report.mentions)
    assert any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


def test_coordinated_rain_toll_and_flood_damage_have_unallocated_scope():
    text = "Chuvas deixaram quatro mortos e enchentes em vários municípios."
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers


def test_future_soil_burial_is_not_an_observed_occurrence():
    text = "Longsor diprediksi menimbun rumah dan menewaskan dua orang."
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions and all(m.role == "forecast" for m in report.mentions)
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


def test_useful_life_of_equipment_is_not_a_human_death():
    assert not extract_reported_impacts(
        "As baterias perderam a vida útil após a enchente.", SOURCE
    )
