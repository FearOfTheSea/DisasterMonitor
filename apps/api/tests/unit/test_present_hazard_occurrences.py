"""Literal present-tense news actions retain actual fatality accounts."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_occurrence import occurrence_role

NOW = datetime(2026, 11, 1, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Historical reporting",
    "https://daily.example/report",
    NOW,
    None,
    NOW,
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(30, NOW)
    )


@pytest.mark.parametrize(
    "text,value",
    [
        (
            "2013 – Hundreds die as a 7.2 magnitude earthquake strikes islands "
            "popular with tourists in the Philippines.",
            "Hundreds",
        ),
        ("Two residents die as a flood hits Brookside.", "Two"),
        ("One person dies as a landslide strikes Eastbrook.", "One"),
        ("Three residents die as a cyclone hits the coast.", "Three"),
        ("Hundreds die as a wildfire strikes the town.", "Hundreds"),
    ],
)
def test_actual_present_action_exposes_the_local_fatality_account(text, value):
    assert occurrence_role(text) == "reported"
    report = assess(text)
    (mention,) = report.mentions
    assert mention.role == "reported"
    assert mention.time is None
    (claim,) = [c for c in mention.claims if c.fact.category == "fatalities"]
    assert claim.fact.value == value
    assert claim.fact.source == SOURCE
    assert claim.excerpt == text
    assert report.article.text == text
    if value == "Hundreds":
        assert "approximate" in claim.qualifiers


@pytest.mark.parametrize(
    "text",
    [
        "If an earthquake strikes the islands, hundreds die.",
        "Hundreds die if an earthquake strikes the islands.",
        "Whenever an earthquake strikes the islands, hundreds die.",
        "Every year a flood hits the town and hundreds die.",
        "An earthquake strikes the islands every decade and hundreds die.",
        "A simulated earthquake strikes the islands and hundreds die.",
        "In a simulation, an earthquake strikes the islands and hundreds die.",
        "Forecast: an earthquake strikes the islands and hundreds die.",
        "An earthquake may strike the islands and hundreds die.",
        "An earthquake does not strike the islands and hundreds die.",
        "A political earthquake strikes the cabinet and hundreds of careers die.",
    ],
)
def test_hypothetical_recurring_negated_and_figurative_actions_are_not_new_occurrences(
    text,
):
    assert occurrence_role(text) not in {"reported", "ongoing", "historical"}
    assert not any(
        c.fact.category == "fatalities" for m in assess(text).mentions for c in m.claims
    )


@pytest.mark.parametrize(
    "text",
    [
        "Hundreds of cattle die as a flood hits the farms.",
        "No people die as a flood hits the town.",
        "Die Erdbeben erschüttern die Inseln.",
    ],
)
def test_nonhuman_zero_and_german_articles_do_not_become_positive_human_tolls(text):
    assert not any(
        c.fact.category == "fatalities" and c.fact.value not in {"0", "Unknown"}
        for m in assess(text).mentions
        for c in m.claims
    )


@pytest.mark.parametrize("reference", ["last major", "previous major"])
def test_present_headline_cannot_absorb_an_explicit_previous_same_place_occurrence(
    reference,
):
    current = "A powerful earthquake hits Brookside."
    earlier = (
        f"The {reference} earthquake to cause widespread damage in Brookside "
        "struck in 1991."
    )
    report = assess(current + " " + earlier)
    assert any(m.excerpt == current and earlier not in m.text for m in report.mentions)
    assert any(m.excerpt == earlier and current not in m.text for m in report.mentions)
    assert report.article.text == current + " " + earlier
