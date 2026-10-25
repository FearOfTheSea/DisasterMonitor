"""A figure of speech or an industrial eruption cannot establish a physical hazard."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Source report", "https://daily.example/report", NOW, None, NOW
)


@pytest.mark.parametrize(
    "text",
    [
        "The refinery fire killed a worker before it was controlled three hours "
        "after its eruption.",
        "The eruption of violence left two people dead.",
        "A chemical eruption at the laboratory injured two workers.",
        "Beloved actress dies as heartbroken tributes flood in.",
        "A flood of tributes followed the actor's death.",
        "Messages flooded in after a singer died.",
        "Condolences flood in after the death of a musician.",
        "A flood of complaints followed the announcement.",
        "Hurricane-force winds toppled a power line.",
        "Hurricane force winds toppled a power line.",
        "Hurricane\N{NON-BREAKING HYPHEN}force winds toppled a power line.",
        "Hurricane-strength winds damaged buildings.",
        "Hurricane-like winds damaged buildings.",
    ],
)
def test_nonliteral_or_nonvolcanic_wording_is_not_a_disaster(text):
    assert disasters_in_text(text) == ()
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )
    assert report.disaster is None
    assert report.eligibility == "unclassified"
    assert report.mentions == ()


@pytest.mark.parametrize(
    ("text", "hazard"),
    [
        ("A volcanic eruption killed two people.", Disaster.VOLCANIC_ERUPTION),
        ("The volcano erupted and killed two people.", Disaster.VOLCANIC_ERUPTION),
        ("Mount Ashvale erupted, killing two people.", Disaster.VOLCANIC_ERUPTION),
        (
            "Victims were killed in the 79AD eruption of Mt. Ashvale.",
            Disaster.VOLCANIC_ERUPTION,
        ),
        (
            "The eruption sent lava through the village.",
            Disaster.VOLCANIC_ERUPTION,
        ),
        (
            "Pyroclastic flows followed the eruption.",
            Disaster.VOLCANIC_ERUPTION,
        ),
        (
            "Hurricane Ada struck the coast with hurricane-force winds.",
            Disaster.TROPICAL_CYCLONE,
        ),
        (
            "Hurricane-force winds caused a grass fire that killed two people.",
            Disaster.WILDFIRE,
        ),
        (
            "A flood killed two people as tributes flood in for the victims.",
            Disaster.FLOOD,
        ),
        ("Floodwater entered a town after a river overflowed.", Disaster.FLOOD),
    ],
)
def test_actual_hazard_wording_survives_nearby_figures_of_speech(text, hazard):
    assert disasters_in_text(text) == (hazard,)


def test_refinery_casualties_do_not_borrow_a_separate_volcano_in_the_same_report():
    text = (
        "A refinery fire killed a worker before it was controlled three hours "
        "after its eruption.\n\n"
        "In a separate event, Mount Ashvale erupted without injuries or deaths."
    )
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )
    eruption = [m for m in report.mentions if m.disaster is Disaster.VOLCANIC_ERUPTION]
    assert eruption
    assert all("refinery" not in m.excerpt.casefold() for m in eruption)
    assert all(
        claim.fact.value == "0"
        for mention in eruption
        for claim in mention.claims
        if claim.fact.category == "fatalities"
    )
