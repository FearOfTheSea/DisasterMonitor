"""A separate accident's toll does not become the neighbouring disaster's toll."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 11, 4, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Flooding closes schools",
    "https://daily.example/flood",
    NOW,
    None,
    NOW,
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )


def fatalities(result):
    return [
        c
        for m in result.mentions
        if m.disaster is Disaster.FLOOD
        for c in m.claims
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Emergency crews responded Sunday to an aircraft crash "
        "that killed nine people, "
        "and widespread flooding on Monday kept the emergency centre active.",
        "Flooding kept the emergency centre active, while a separate aircraft crash "
        "killed nine people.",
        "Floods and a separate aircraft crash killed eleven people.",
        "Eleven people died in floods and a separate aircraft crash.",
    ],
)
def test_separate_or_joint_accident_toll_stays_unallocated_to_flood(text):
    result = assess(text)
    assert result.mentions
    assert result.article.text == text
    assert not fatalities(result)
    assert not result.fatality_evidence


def test_explicit_flood_toll_survives_a_separate_accident_toll():
    text = (
        "Flooding killed two people, while a separate aircraft crash "
        "killed nine people."
    )
    claims = fatalities(assess(text))
    assert claims and all(c.fact.value == "two" for c in claims)


@pytest.mark.parametrize(
    "text",
    [
        "Flooding damaged a runway and caused an aircraft crash "
        "that killed nine people.",
        "An aircraft crash killed nine people, and investigators said flooding "
        "caused the crash.",
        "An aircraft crash killed nine people, and investigators said flooding "
        "may have caused the accident.",
        "A driver died in a crash after fleeing the flood.",
    ],
)
def test_attributed_disaster_related_accident_accounts_remain_available(text):
    assert fatalities(assess(text))
