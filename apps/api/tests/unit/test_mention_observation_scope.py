"""Felt-area references cannot acquire the report country's impact accounts."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

NOW = datetime(2026, 10, 18, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Exampleland earthquake update",
    "https://news.example/report",
    NOW,
    None,
    NOW,
)


@pytest.mark.parametrize("nearby", ["neighbouring", "neighboring", "nearby"])
def test_regional_descriptors_keep_separate_country_accounts_separate(nearby):
    mentions = extract_mentions(
        "At least 81 people were killed by flooding in northern Exampleland's "
        "Green Valley state, officials said on Monday. "
        "The state government said 46 people were injured. "
        "Flooding also affected the eastern state of Riverton, where 75000 people "
        "were evacuated. "
        f"In {nearby} Otherland, 21 people died in weather-related incidents.",
        SOURCE,
    )
    first = next(m for m in mentions if "81 people" in m.excerpt)
    assert first.place.wording == "Exampleland's Green Valley state"
    assert first.time is None
    assert {c.fact.value for c in first.claims} == {"81", "46"}
    assert "Otherland" not in first.text
    other = next(m for m in mentions if m.place and m.place.wording == "Riverton")
    assert "75000 people were evacuated" in other.text
    assert "75000" not in first.text
    assert not any(c.fact.category == "fatalities" for c in other.claims)
    # A different country's weather-related deaths do not establish flood deaths.
    assert all(c.fact.value != "21" for m in mentions for c in m.claims)
    assert any("21 people died" in m.text for m in mentions)


def test_specific_site_after_at_is_a_descriptive_place():
    (mention,) = extract_mentions(
        "A wildfire killed four responders at Pine Ridge.", SOURCE
    )
    assert mention.place.wording == "Pine Ridge"


def test_foreign_mixed_hazard_context_cannot_inherit_the_headline_country():
    mentions = extract_mentions(
        "Floods killed 81 people in Firstland. "
        "In neighbouring Otherland, 21 people died in weather-related incidents. "
        "Five others were injured, while floods and landslides damaged roads.",
        replace(SOURCE, title="Floods in Firstland"),
    )
    fragments = [m for m in mentions if "landslides damaged" in m.text]
    assert fragments
    assert all(m.place is None or m.place.wording != "Firstland" for m in fragments)


@pytest.mark.parametrize("hazard", ["Landslides", "Floods", "Wildfires"])
def test_unknown_place_occurrence_does_not_acquire_a_later_local_outage(hazard):
    mentions = extract_mentions(
        f"{hazard} destroyed several houses. "
        "More than 45000 households in Coastland were still without electricity, "
        "while 460 houses were damaged. "
        "Authorities also reported damaged roads.",
        replace(SOURCE, title="Storm aftermath"),
    )
    occurrence = next(m for m in mentions if "destroyed several houses" in m.excerpt)
    assert occurrence.place is None
    assert not occurrence.claims
    assert "45000" not in occurrence.text
    fragment = next(m for m in mentions if "45000" in m.text)
    assert fragment.place.wording == "Coastland"
    assert fragment.role == "uncertain"
    assert not fragment.claims
    assert any("scope changed" in notice for notice in fragment.notices)


def test_unlocated_occurrence_keeps_unqualified_contiguous_impacts():
    mentions = extract_mentions(
        "Landslides destroyed houses. Officials reported six deaths.", SOURCE
    )
    assert any(c.fact.value == "six" for m in mentions for c in m.claims)


def test_named_storm_link_can_retain_a_later_explicit_local_account():
    mentions = extract_mentions(
        "Typhoon Alpha swept through the region. "
        "In Coastland, Alpha damaged electricity networks.",
        SOURCE,
    )
    assert any(c.fact.category == "electricity" for m in mentions for c in m.claims)


def test_felt_extent_does_not_relocate_national_impacts_to_neighbor_country():
    article = DiscoveryArticle(
        SOURCE,
        "On 9 October 2026 a magnitude 7.4 earthquake struck Ridge Province. "
        "As of 11 October, impacts were reported across 16 provinces, while the "
        "earthquake was felt across Exampleland and reported in Neighborland. "
        "According to the national authority, 331 deaths and 45 injuries "
        "were reported.",
        location="Exampleland",
    )
    report = assess_article(
        article,
        ReportingInterval.at_start(30, NOW),
        country_names=frozenset({"exampleland", "neighborland"}),
    )
    accounts = [(m, c) for m in report.mentions for c in m.claims]
    assert accounts
    assert all(m.place.wording == "Exampleland" for m, c in accounts)
    assert all(c.fact.reported_location == "Exampleland" for m, c in accounts)
    assert all(
        not m.claims for m in report.mentions if m.place.wording == "Ridge Province"
    )


def test_direct_damage_in_a_neighbor_remains_a_local_account():
    article = DiscoveryArticle(
        SOURCE,
        "An earthquake was felt in Neighborland and destroyed roads in Riverton. "
        "Two people died in Riverton.",
        location="Exampleland",
    )
    report = assess_article(article, ReportingInterval.at_start(30, NOW))
    assert any(m.claims for m in report.mentions)
    assert all(m.place.wording == "Riverton" for m in report.mentions if m.claims)


def test_felt_only_report_with_no_country_context_does_not_allocate_totals():
    source = SourceReference(
        "news",
        "Daily",
        "Regional update",
        "https://news.example/regional",
        NOW,
        None,
        NOW,
    )
    article = DiscoveryArticle(
        source,
        "The earthquake was felt in Neighborland. "
        "The national authority reported 12 deaths.",
    )
    report = assess_article(article, ReportingInterval.at_start(30, NOW))
    assert not any(m.claims for m in report.mentions)
