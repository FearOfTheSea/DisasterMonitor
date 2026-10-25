"""Resolve a nonhuman death pronoun only from its immediate source antecedent."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 25, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Wildfire effects", "https://daily.example/report", NOW, None, NOW
)


def fatalities(text):
    return tuple(
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Trees were being killed off by the wildfire.",
        "Climate change is causing forested lands to die off. "
        "They are being killed off by rising temperatures and forest fires.",
        "Cattle died in the flood. They were killed by the rising water.",
        "The drought killed crops. They were reported dead across the valley.",
    ],
)
def test_immediate_nonhuman_death_antecedent_cannot_establish_human_fatalities(text):
    assert fatalities(text) == ()
    assessed = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )
    assert assessed.article.text == text
    assert assessed.fatality_evidence == ()
    assert not any(
        c.fact.category == "fatalities" for m in assessed.mentions for c in m.claims
    )


def test_quoted_tree_loss_context_remains_available_without_a_human_death_claim():
    text = (
        "“Climate change is causing forested lands to die off,” the artist wrote. "
        "“They are being killed off by rising temperatures, forest fires and trees "
        "that are more susceptible to beetles.”\nThe installation was beautiful."
    )
    assessed = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )
    assert assessed.article.text == text
    assert assessed.mentions
    assert all(not m.claims for m in assessed.mentions)
    assert any("They are being killed off" in m.text for m in assessed.mentions)


@pytest.mark.parametrize(
    "text",
    [
        "People fled the wildfire. They were killed by falling trees.",
        "They were killed by the wildfire.",
        "Cattle and two workers died in the flood. They were killed by rising water.",
        "John and cattle died in the flood. They were killed by rising water.",
        "Cattle died in the flood. Two people were killed while rescuing them.",
        "Trees died in the wildfire. Residents entered the area. "
        "They were killed by falling trees.",
        "Trees died in the wildfire.\n\n## Rescue operation\n"
        "They were killed by falling trees.",
        "Trees died in the wildfire. They and Marta were killed by falling branches.",
        "Trees died in the wildfire. They died and Marta was killed by the blaze.",
        "Trees died in the wildfire. They were killed along with Marta.",
        "Trees died in the wildfire. They were killed, including a driver.",
    ],
)
def test_human_or_unresolved_pronoun_accounts_remain_attributed(text):
    claims = fatalities(text)
    assert claims
    assert all(c.fact.value not in {"50", "52"} for c in claims)


def test_nonhuman_pronoun_does_not_hide_a_later_separate_human_fatality():
    text = (
        "Trees died in the wildfire. They were killed by the extreme heat. "
        "Two workers died in the wildfire."
    )
    (claim,) = fatalities(text)
    assert claim.fact.value == "Two"
    assert claim.excerpt == "Two workers died in the wildfire."


def test_repeated_pronoun_wording_with_different_referents_remains_unresolved():
    sentence = "They were killed in the flood."
    text = f"Cattle died in the flood. {sentence} Two people fled. {sentence}"
    claims = fatalities(text)
    assert any(c.excerpt == sentence for c in claims)
    assessed = assess_article(
        DiscoveryArticle(replace(SOURCE, title="Flood effects"), text),
        ReportingInterval.at_start(1, NOW),
    )
    assert any(c.excerpt == sentence for m in assessed.mentions for c in m.claims)


def test_masking_a_joined_nonhuman_quote_preserves_the_following_human_account():
    text = (
        "Trees died in the wildfire. “They were killed by the heat.”\n"
        "Two workers died in the wildfire."
    )
    assessed = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )
    claims = [c for m in assessed.mentions for c in m.claims]
    assert claims
    assert all(c.fact.value == "Two" for c in claims)
