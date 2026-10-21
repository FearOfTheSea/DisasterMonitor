"""Physical grass fires qualify; military context does not turn them into drills."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Regional news", "https://news.example/report", NOW, None, NOW
)


def test_grass_fire_with_actual_training_casualties_is_a_physical_wildfire():
    mentions = extract_mentions(
        "A grass fire killed four soldiers and injured 39 people at North Plains "
        "during a live-fire combat training exercise on 17 October 2026.",
        SOURCE,
    )
    assert len(mentions) == 1
    mention = mentions[0]
    assert mention.disaster is Disaster.WILDFIRE
    assert mention.role == "reported"
    assert mention.place.wording == "North Plains"
    assert mention.time.start == datetime(2026, 10, 17, tzinfo=UTC)
    assert {(c.fact.category, c.fact.value) for c in mention.claims} == {
        ("fatalities", "four"),
        ("injuries", "39"),
    }


def test_observed_grass_fire_keeps_contiguous_reported_casualties():
    mentions = extract_mentions(
        "On Saturday, officials in North Plains observed a grass fire. "
        "Four soldiers were killed and 39 people were injured when the wind shifted.",
        SOURCE,
    )
    assert len(mentions) == 1
    mention = mentions[0]
    assert mention.role == "reported"
    assert mention.place.wording == "North Plains"
    assert mention.time.start == datetime(2026, 10, 17, tzinfo=UTC)
    assert {(c.fact.category, c.fact.value) for c in mention.claims} == {
        ("fatalities", "Four"),
        ("injuries", "39"),
    }


@pytest.mark.parametrize("action", ["ignited", "spread", "burned", "burnt"])
def test_past_physical_vegetation_fire_action_can_establish_occurrence(action):
    (mention,) = extract_mentions(
        f"A grass fire {action} in North Plains on Saturday.", SOURCE
    )
    assert mention.role == "reported"
    assert mention.time.start == datetime(2026, 10, 17, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    [
        "A simulation of a grass fire in North Plains tested emergency teams.",
        "Officials are preparing for grass fires in North Plains.",
        "A grass fire drill in North Plains tested a response "
        "to four simulated deaths.",
    ],
)
def test_simulated_or_expected_grass_fires_do_not_claim_actual_casualties(text):
    mentions = extract_mentions(text, SOURCE)
    assert mentions
    assert all(m.role == "forecast" and not m.claims for m in mentions)


def test_generic_grass_fire_description_does_not_establish_current_occurrence():
    (mention,) = extract_mentions(
        "A grass fire spreads through dry grass, weeds and shrubs.", SOURCE
    )
    assert mention.role == "uncertain"
    assert not mention.claims


@pytest.mark.parametrize("place", ["a factory", "a house", "a vehicle"])
def test_fire_in_a_structure_or_vehicle_is_not_automatically_a_wildfire(place):
    assert not extract_mentions(f"A fire killed four people in {place}.", SOURCE)
