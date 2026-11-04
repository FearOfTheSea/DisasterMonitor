"""Present-tense reporting must not turn predicted deaths into observed losses."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 11, 4, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Report", "https://daily.example/report", NOW, None, NOW
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
        "A flood could kill twenty people.",
        "A flood may kill twenty people.",
        "A flood might kill twenty people.",
        "A flood can kill twenty people.",
        "A flood would kill twenty people.",
        "Officials warn the flood will kill twenty people.",
        "The flood is going to kill twenty people.",
        "The flood is expected to kill twenty people.",
        "The flood is likely to kill twenty people.",
    ],
)
def test_predicted_killing_does_not_become_a_reported_fatality_count(text):
    assert not fatalities(text)


def test_predicted_predicate_does_not_hide_a_reported_death_in_the_same_sentence():
    text = "The flood kills two people, but further flooding could kill twenty people."
    (claim,) = fatalities(text)
    assert claim.fact.value == "two"
    assert claim.excerpt == text


@pytest.mark.parametrize("modal", ["may", "might", "could"])
def test_uncertain_past_deaths_are_retained_with_uncertainty(modal):
    text = f"The flood {modal} have killed two people."
    (claim,) = fatalities(text)
    assert claim.fact.value == "two"
    assert "uncertain" in claim.qualifiers
    assert claim.excerpt == text
