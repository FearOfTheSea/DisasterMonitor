"""Literal life-ending reports expose occurrences without inventing a family toll."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_occurrence import occurrence_role
from disaster_monitor.domain.regional_accounts import regional_fatality_account

NOW = datetime(2026, 11, 1, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Boletín local", "https://daily.example/report", NOW, None, NOW
)


@pytest.mark.parametrize(
    "hazard",
    [
        "El terremoto",
        "La inundación",
        "El incendio forestal",
        "El deslizamiento de tierra",
        "La sequía",
        "El huracán",
        "La erupción volcánica",
    ],
)
def test_actual_life_ending_wording_exposes_a_reported_hazard(hazard):
    text = f"{hazard} acabó con la vida de su esposa y sus dos hijos."
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert occurrence_role(text) == "reported"
    (mention,) = report.mentions
    assert mention.role == "reported"
    assert mention.excerpt == text
    assert mention.time is None
    assert mention.place is None
    (claim,) = mention.claims
    assert claim.fact.category == "fatalities"
    assert claim.fact.value == "Reported; count unknown"
    assert claim.fact.source == SOURCE
    assert claim.excerpt == text
    assert report.article.text == text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("El huracán acabó con la vida de dos personas.", "2"),
        ("Las inundaciones acabaron con la vida de cuatro bomberos.", "4"),
        (
            "El terremoto acabó con la vida de su hermano de 74 años.",
            "Reported; count unknown",
        ),
    ],
)
def test_only_an_explicit_toll_is_normalized(text, expected):
    account = regional_fatality_account(text)
    assert account is not None and account.value == expected


@pytest.mark.parametrize(
    "text",
    [
        "El terremoto no acabó con la vida de su esposa.",
        "En un simulacro, el terremoto acabó con la vida de dos personas.",
        "Se prevé que el terremoto podría acabar con la vida de dos personas.",
        "La inundación acabó con la vida de veinte vacas.",
        "El terremoto acabó con la vida útil de las baterías.",
        "El terremoto acabó con la vida política del alcalde.",
    ],
)
def test_zero_forecast_nonhuman_and_figurative_wording_are_not_positive_tolls(text):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert not any(
        claim.fact.category == "fatalities" and claim.fact.value not in {"0", "Unknown"}
        for mention in report.mentions
        for claim in mention.claims
    )
    assert report.article.text == text


def test_a_byline_cannot_keep_a_later_literal_death_account_uncertain():
    body = (
        "## Terremoto\nPor La Redacción\n"
        "El terremoto acabó con la vida de su esposa y sus dos hijos."
    )
    report = assess_article(
        DiscoveryArticle(SOURCE, body), ReportingInterval.at_start(3, NOW)
    )
    reported = [mention for mention in report.mentions if mention.role == "reported"]
    assert len(reported) == 1
    assert reported[0].excerpt.startswith("El terremoto acabó")
    assert reported[0].claims[0].fact.value == "Reported; count unknown"
    assert report.article.source == SOURCE and report.article.text == body


def test_animal_and_family_accounts_remain_unallocated():
    text = "El terremoto acabó con la vida de veinte vacas y de su esposa."
    account = regional_fatality_account(text)
    assert account is not None and account.value == "Unknown"
    assert "scope unresolved" in account.qualifiers
