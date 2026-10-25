"""A reported English count retains the full number, never its final component."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Source", "https://daily.example/report", NOW, None, NOW
)


def fatalities(text):
    return [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("Forty-five", "Forty-five"),
        ("forty five", "forty five"),
        ("twenty-one", "twenty-one"),
        ("ninety-nine", "ninety-nine"),
        ("eleven", "eleven"),
        ("nineteen", "nineteen"),
        ("one hundred and forty-five", "one hundred and forty-five"),
        ("two hundred", "two hundred"),
        ("one thousand two hundred", "one thousand two hundred"),
        ("fifty million", "fifty million"),
        ("50 million", "50 million"),
        ("1,245", "1245"),
    ],
)
def test_full_number_before_person_and_casualty_predicate(number, expected):
    text = f"{number} people died in the flood."
    (claim,) = fatalities(text)
    assert claim.fact.value == expected
    assert claim.excerpt == text


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("forty-five", "forty-five"),
        ("forty\N{NON-BREAKING HYPHEN}five", "forty\N{NON-BREAKING HYPHEN}five"),
        ("seventeen", "seventeen"),
        ("one hundred and forty-five", "one hundred and forty-five"),
        ("two thousand and forty-five", "two thousand and forty-five"),
        ("50 million", "50 million"),
    ],
)
def test_full_number_after_killed(number, expected):
    text = f"The flood killed {number} people."
    (claim,) = fatalities(text)
    assert claim.fact.value == expected


@pytest.mark.parametrize(
    "text",
    [
        "Forty-five people died, but officials later corrected the toll to 45 deaths.",
        "One hundred and forty-five people died; the final toll was 145 deaths.",
    ],
)
def test_repeated_equivalent_counts_do_not_become_a_conflict(text):
    # The semicolon example remains separate source sentences, each with one toll.
    claims = fatalities(text)
    assert claims
    assert all(c.fact.value != "Unknown" for c in claims)


@pytest.mark.parametrize(
    "text",
    [
        "Forty-five people died in the flood and three people died in the earthquake.",
        "The flood killed twenty-five workers and three residents.",
    ],
)
def test_distinct_populations_remain_unallocated(text):
    (claim,) = fatalities(text)
    assert claim.fact.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers


@pytest.mark.parametrize(
    "text",
    [
        "The flood killed a 45-year-old man.",
        "The flood killed a man on October 19.",
        "Three people died in the flood while forty-five people cleared roads.",
    ],
)
def test_age_date_and_unaffected_population_do_not_supply_a_toll(text):
    claims = fatalities(text)
    assert claims
    assert all(c.fact.value not in {"45", "19", "forty-five"} for c in claims)


@pytest.mark.parametrize("number", ["eleven", "seventeen", "forty"])
def test_supported_number_words_also_supply_the_retained_fatality_passage(number):
    text = f"The flood killed {number} people."
    result = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )
    assert result.fatality_evidence == (text,)


@pytest.mark.parametrize(
    "text",
    [
        "The flood killed 1.5 million people.",
        "The flood killed 1,5 million people.",
        "One thousand million people died; authorities reported one billion deaths.",
    ],
)
def test_unsupported_number_forms_never_become_an_incorrect_component_or_equivalence(
    text,
):
    claims = fatalities(text)
    assert claims
    assert all(
        c.fact.value not in {"1", "5 million", "15 million", "1000"} for c in claims
    )


def test_nonstandard_scale_order_is_not_equal_to_its_first_component():
    text = "One thousand million people died, but officials reported 1000 deaths."
    (claim,) = fatalities(text)
    assert claim.fact.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers
