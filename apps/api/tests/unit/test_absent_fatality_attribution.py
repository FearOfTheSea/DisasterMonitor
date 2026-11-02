"""Missing causal attribution is neither a zero toll nor an actual hazard death."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 11, 1, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Earthquake reporting",
    "https://daily.example/report",
    NOW,
    None,
    NOW,
)


def fatalities(text):
    return [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Officials did not attribute any deaths to the quakes.",
        "Officials have not attributed any deaths to the earthquake.",
        "Officials could not link any fatalities to the earthquake.",
        "No deaths have been attributed to the earthquake.",
        "No fatalities were linked to the earthquake.",
        "Officials attributed no deaths to the earthquake.",
        "Officials did not attribute the two deaths to the earthquake.",
        "The two deaths were not attributed to the earthquake.",
    ],
)
def test_absent_causal_attribution_keeps_unknown_and_source_wording(text):
    (claim,) = fatalities(text)
    assert claim.fact.value == "Unknown"
    assert "uncertain" in claim.qualifiers
    assert "no fatality attribution" in claim.qualifiers
    assert claim.fact.source == SOURCE
    assert claim.excerpt == text


def test_observed_damage_clause_does_not_turn_missing_attribution_into_actual_deaths():
    text = (
        "Officials did not attribute any deaths to the quakes but reported "
        "damages in all 10 provinces and two Indigenous territories."
    )
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(30, NOW)
    )
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert claims and {c.fact.value for c in claims} == {"Unknown"}
    assert all("no fatality attribution" in c.qualifiers for c in claims)
    assert report.article.text == text


@pytest.mark.parametrize(
    "text",
    [
        "Officials did not attribute any deaths to the earthquake, "
        "but residents reported two deaths in the earthquake.",
        "No deaths were attributed to the earthquake; "
        "residents reported two deaths in the earthquake.",
        "Residents reported two deaths in the earthquake, "
        "but officials did not attribute any deaths to the earthquake.",
    ],
)
def test_contrasting_actual_account_and_missing_attribution_both_remain_visible(text):
    claims = fatalities(text)
    assert {c.fact.value.casefold() for c in claims} == {"unknown", "two"}
    positive = next(c for c in claims if c.fact.value.casefold() == "two")
    unknown = next(c for c in claims if c.fact.value == "Unknown")
    assert "no fatality attribution" not in positive.qualifiers
    assert "no fatality attribution" in unknown.qualifiers
    assert "residents reported two deaths" in positive.excerpt.casefold()
    assert positive.excerpt in text and unknown.excerpt in text


@pytest.mark.parametrize(
    "text,value",
    [
        ("No people died in the earthquake.", "0"),
        ("Zero people died in the earthquake.", "0"),
        ("Officials attributed two deaths to the earthquake.", "two"),
        (
            "Two people died during the earthquake; "
            "their exact cause of death remains uncertain.",
            "Two",
        ),
        (
            "A person died in the earthquake, "
            "although the precise cause remains uncertain.",
            "Reported; count unknown",
        ),
    ],
)
def test_actual_deaths_uncertain_cause_and_explicit_zero_keep_their_accounts(
    text, value
):
    claims = fatalities(text)
    assert any(c.fact.value == value for c in claims)
    assert all("no fatality attribution" not in c.qualifiers for c in claims)


def test_clauses_do_not_bypass_the_whole_source_sentence_length_bound():
    text = (
        "Officials did not attribute any deaths to the earthquake; "
        + "the full qualifications remain necessary " * 20
        + "but residents reported two deaths in the earthquake."
    )
    assert fatalities(text) == []
