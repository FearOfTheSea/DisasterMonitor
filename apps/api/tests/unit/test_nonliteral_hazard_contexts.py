"""Nonliteral wording does not erase co-occurring physical hazard reporting."""

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


@pytest.mark.parametrize(
    "text",
    [
        "The party won a parliamentary election by a landslide.",
        "The candidate won the governorship in a landslide.",
        "Pat defeated Jordan in a landslide.",
        "A landslide victory followed weeks of campaigning.",
        "All the pain of her past came flooding back.",
        'The post said: "Flood the zone with our own people."',
        "The Earthquake K32 wood chipper shredded branches.",
        "Earthquake’s K32 wood chipper performed well.",
        "The company began a 3D seismic campaign offshore.",
        "Seismic and G&G, land, capitalized G&A and other costs increased.",
        "Seismic and G&G costs increased.",
        "The Earthquake and Tsunami Geology Team issued advice.",
        "A councillor was remembered.\n"
        "READ MORE: Funding cuts affect flood prevention\n"
        "Colleagues praised her public service.",
        "Fighting Ebola is like fighting a wildfire.",
    ],
)
def test_nonliteral_or_related_link_wording_is_not_a_physical_hazard(text):
    assert not disasters_in_text(text)


@pytest.mark.parametrize(
    "text,hazard",
    [
        (
            "A landslide killed two villagers. "
            "The party won the election by a landslide.",
            Disaster.LANDSLIDE,
        ),
        (
            "Memories of the flood came flooding back.",
            Disaster.FLOOD,
        ),
        (
            "Floodwaters came flooding back into the village.",
            Disaster.FLOOD,
        ),
        (
            "An earthquake damaged the factory that makes "
            "Earthquake K32 wood chippers.",
            Disaster.EARTHQUAKE,
        ),
        (
            "A seismic survey followed the earthquake that damaged the city.",
            Disaster.EARTHQUAKE,
        ),
        (
            "Wildfires destroyed homes. Fighting Ebola is like fighting a wildfire.",
            Disaster.WILDFIRE,
        ),
        (
            "News from the forest says flames spread like a wildfire.",
            Disaster.WILDFIRE,
        ),
        (
            "The election debate discussed the response to Hurricane Helen in 2024.",
            Disaster.TROPICAL_CYCLONE,
        ),
    ],
)
def test_literal_reporting_survives_nonliteral_wording_elsewhere(text, hazard):
    assert disasters_in_text(text) == (hazard,)


def test_a_retained_history_article_without_a_physical_hazard_has_no_mentions():
    now = datetime(2026, 11, 4, tzinfo=UTC)
    source = SourceReference(
        "news", "Daily", "On this day", "https://daily.example/history", now, None, now
    )
    text = (
        "1954: An artist died.\n"
        "2002: A party won an election by a landslide.\n"
        "2004: A former soldier returned to his family."
    )
    result = assess_article(
        DiscoveryArticle(source, text), ReportingInterval.at_start(1, now)
    )
    assert result.article.text == text
    assert not result.mentions
