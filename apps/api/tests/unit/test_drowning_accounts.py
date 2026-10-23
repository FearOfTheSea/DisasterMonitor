"""Completed drowning accounts are distinct from rescue and missing-person wording."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.collection import (
    fatality_hint_needs_followup,
    lead_retrieval_priority,
)
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 22, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Flood report", "https://daily.example/flood", NOW, None, NOW
)


@pytest.mark.parametrize(
    "text,count",
    [
        ("Seven people drowned after rain triggered flooding.", "Seven"),
        ("Two people drowned in the flood while four others were rescued.", "Two"),
        ("Response workers said seven people drowned in the flood.", "seven"),
    ],
)
def test_completed_drowning_is_an_attributed_fatality_in_both_projections(text, count):
    assessed = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(7, NOW)
    )
    assert assessed.fatality_evidence == (text,)
    assert any(m.role == "reported" for m in assessed.mentions)
    claims = [
        c
        for m in assessed.mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    ]
    assert [c.fact.value for c in claims] == [count]
    assert claims[0].excerpt == text
    lead = NewsFeedItem(
        "hint", "Index", "Flood killed seven", SOURCE.canonical_url, None, None
    )
    assert not fatality_hint_needs_followup(lead, assessed.article)


@pytest.mark.parametrize(
    "text",
    [
        "Two people nearly drowned in the flood.",
        "Two people almost drowned in the flood but survived.",
        "Three people are feared drowned in the flood.",
        "Three people are believed to have drowned in the flood.",
        "Two people drowned but were resuscitated after the flood.",
        "Two people drowned and were successfully revived after the flood.",
        "Seven cows drowned in the flood.",
        "Floods drowned seven cows.",
        "No one drowned in the flood.",
    ],
)
def test_nonfatal_unknown_or_animal_drowning_does_not_establish_human_deaths(text):
    assessed = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(7, NOW)
    )
    assert assessed.fatality_evidence == ()
    assert not any(
        c.fact.category == "fatalities" and c.fact.value not in ("0", "Unknown")
        for m in assessed.mentions
        for c in m.claims
    )
    assert assessed.article.text == text


def test_near_drowning_context_does_not_hide_a_different_actual_fatality():
    text = "Two people died in the flood while another person nearly drowned."
    claims = [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]
    assert [c.fact.value for c in claims] == ["Two"]
    assert claims[0].excerpt == text


def test_drowning_forecast_is_not_projected_as_an_actual_death():
    text = "The drill simulates a flood in which three people drowned."
    assessed = assess_article(
        DiscoveryArticle(replace(SOURCE, title="Flood drill"), text),
        ReportingInterval.at_start(7, NOW),
    )
    assert assessed.fatality_evidence == ()


def test_completed_drowning_hint_is_prioritized_until_publisher_evidence_resolves_it():
    lead = NewsFeedItem(
        "hint",
        "Index",
        "Seven people drowned in a flood",
        SOURCE.canonical_url,
        None,
        None,
    )
    assert lead_retrieval_priority(lead) == 2
    assert fatality_hint_needs_followup(
        lead, DiscoveryArticle(SOURCE, "Floods damaged homes.")
    )
    near = replace(lead, title="Seven people nearly drowned in a flood")
    assert lead_retrieval_priority(near) == 0
    assert (
        lead_retrieval_priority(replace(lead, title="No one drowned in a flood")) == 0
    )


def test_nonfatal_english_wording_does_not_hide_a_regional_fatality_account():
    text = "Dos personas murieron en la inundación y one person nearly drowned."
    claims = [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]
    assert [c.fact.value for c in claims] == ["2"]
    assert claims[0].excerpt == text
