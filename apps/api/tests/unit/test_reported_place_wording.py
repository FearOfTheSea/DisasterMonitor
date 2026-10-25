"""Reported geography needs a place phrase, not headline or subscription grammar."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 23, tzinfo=UTC)


def assess(text, title="Regional situation report"):
    source = SourceReference(
        "news", "Daily", title, "https://daily.example/report", NOW, None, NOW
    )
    return assess_article(
        DiscoveryArticle(source, text), ReportingInterval.at_start(1, NOW)
    )


def places(result):
    return {m.place.wording for m in result.mentions if m.place}


@pytest.mark.parametrize("verb", ["Hits", "Strikes"])
def test_a_headline_impact_verb_finds_the_place_after_an_initial_quantifier(verb):
    result = assess(
        "At least two people died in the earthquake.",
        f"At Least Two Killed After Earthquake {verb} Lakeview",
    )
    assert result.mentions
    assert places(result) == {"Lakeview"}
    assert any(
        c.fact.value.casefold() == "two"
        for m in result.mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    )


@pytest.mark.parametrize(
    "title", ["Earthquake Leaves At Least Two Dead", "Flood-hit Town"]
)
def test_generic_headline_words_do_not_invent_a_named_location(title):
    result = assess("A flood killed two people.", title)
    assert result.mentions
    assert not places(result)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("in the Western region of Lakeview", "Lakeview"),
        ("near the remote province of Riverton", "Riverton"),
        ("in the eastern coastal province of Ashford", "Ashford"),
    ],
)
def test_explicit_administrative_location_beats_a_later_state_media_attribution(
    phrase, expected
):
    result = assess(
        f"An earthquake {phrase} killed two people, according to Western state media."
    )
    assert places(result) == {expected}


def test_state_media_without_a_reported_place_does_not_name_a_location():
    result = assess(
        "An earthquake killed two people, according to Western state media."
    )
    assert result.mentions
    assert not places(result)


@pytest.mark.parametrize(
    "invitation",
    [
        "Interested in Fraud?",
        "Interested in Floods in Hilltown?",
        "Subscribe to Flood Alerts in Hilltown",
        "Sign up for News in Hilltown",
    ],
)
def test_subscription_heading_cannot_supply_geography_to_the_following_article(
    invitation,
):
    text = f"## {invitation}\nGet automatic alerts.\nFloods killed two people."
    result = assess(text)
    assert result.mentions
    assert not places(result)
    assert result.article.text == text
    assert any(
        c.fact.value == "two"
        for m in result.mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    )


def test_an_actual_hazard_heading_still_supplies_its_reported_place():
    result = assess("## Floods in Lakeview\nTwo people died.")
    assert places(result) == {"Lakeview"}
    assert any(
        c.fact.value == "Two"
        for m in result.mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    )


@pytest.mark.parametrize("connector", ["After", "Before", "During", "Following"])
def test_a_headline_causal_or_temporal_tail_is_not_part_of_the_place(connector):
    result = assess(
        "Flooding killed two people.",
        f"Two Killed in Lakeview {connector} Heavy Flooding",
    )
    assert places(result) == {"Lakeview"}


def test_a_trailing_conjunction_is_not_part_of_the_reported_place():
    result = assess("Floods in Lakeview and nearby villages killed two people.")
    assert places(result) == {"Lakeview"}


@pytest.mark.parametrize(
    "name",
    [
        "Townsville",
        "State College",
        "McAllen",
        "Trinidad and Tobago",
        "Bath and North East Somerset",
    ],
)
def test_named_compound_places_and_internal_conjunctions_remain_literal(name):
    result = assess(f"Floods hit {name}. Two people died.")
    assert places(result) == {name}


@pytest.mark.parametrize("tail", ["Minutes Later", "Hours Earlier", "Days Later"])
def test_headline_relative_time_is_not_part_of_the_place(tail):
    result = assess(
        "An earthquake killed two people.", f"Earthquake Hits Lakeview {tail}"
    )
    assert places(result) == {"Lakeview"}


@pytest.mark.parametrize("wording", ["November and December", "Thursday", "Sept"])
def test_a_calendar_word_or_range_does_not_become_a_place(wording):
    result = assess(f"Floods occurred in {wording}. Two people died.")
    assert result.mentions
    assert not places(result)


@pytest.mark.parametrize("name", ["Thursday Island", "Mayfield"])
def test_weekday_or_month_name_parts_do_not_erase_a_real_compound_place(name):
    result = assess(f"Floods hit {name}. Two people died.")
    assert places(result) == {name}


def test_later_city_damage_does_not_relocate_a_broader_fatality_account():
    text = (
        "An earthquake hit Lakeview region, killing sixteen people and "
        "collapsing homes in the northern regional city of Riverton."
    )
    result = assess(text)
    fatal = [
        m
        for m in result.mentions
        if any(c.fact.category == "fatalities" for c in m.claims)
    ]
    assert fatal
    assert all(m.place and m.place.wording == "Lakeview" for m in fatal)
    assert all(
        c.fact.reported_location == "Lakeview"
        for m in fatal
        for c in m.claims
        if c.fact.category == "fatalities"
    )
