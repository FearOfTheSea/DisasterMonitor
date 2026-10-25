"""Deaths in an accident that ignites a fire are not automatically fire deaths."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Wildfire report", "https://daily.example/report", NOW, None, NOW
)


def report(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )


def fatalities(result):
    return [
        c
        for m in result.mentions
        if m.disaster is Disaster.WILDFIRE
        for c in m.claims
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "A rollover crash in rural Forest County killed a passenger "
        "and sparked a wildfire.",
        "A collision killed two people and ignited a forest fire.",
        "The wreck left a passenger dead and then started a grass fire.",
        "A crash killed a passenger and triggered a bushfire that burned 100 hectares.",
    ],
)
def test_a_fatal_precursor_accident_remains_source_context_without_a_fire_death(text):
    result = report(text)
    assert result.mentions
    assert result.article.text == text
    assert not fatalities(result)
    assert not result.fatality_evidence


@pytest.mark.parametrize(
    "text",
    [
        "Wildfire smoke caused a crash that killed two people.",
        "A collision caused by wildfire smoke killed two people "
        "and sparked another wildfire.",
        "Two people died in a crash after fleeing the wildfire.",
        "A wildfire killed two people when flames engulfed their car.",
    ],
)
def test_actual_or_attributed_fire_related_traffic_deaths_remain_available(text):
    assert fatalities(report(text))


def test_a_separate_actual_wildfire_toll_survives_the_precursor_accident():
    text = (
        "A crash killed a passenger and sparked a wildfire. "
        "The wildfire later killed two firefighters."
    )
    claims = fatalities(report(text))
    assert claims
    assert all("passenger" not in c.excerpt for c in claims)
    assert any(c.fact.value == "two" for c in claims)
