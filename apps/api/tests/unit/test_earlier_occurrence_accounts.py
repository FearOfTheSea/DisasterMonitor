"""A later physical occurrence cannot borrow an earlier occurrence's impacts."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.events import point_event_geometry
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 14, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "New flood in Brookside",
    "https://daily.example/report",
    NOW,
    None,
    NOW,
)


def assess(text, **metadata):
    return assess_article(
        DiscoveryArticle(SOURCE, text, **metadata), ReportingInterval.at_start(3, NOW)
    )


def fatalities(report):
    return [
        (m, c)
        for m in report.mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    ]


def test_earlier_landslide_deaths_do_not_take_the_later_mud_wave_date():
    text = (
        "After the enormous landslide that caused thousands of deaths and missing "
        "people last August, yesterday, Sunday 11 October, a huge wave of mud and "
        "debris overwhelmed the valley, sweeping away buildings and bridges."
    )
    report = assess(text)
    assert report.article.text == text
    assert fatalities(report)
    for mention, claim in fatalities(report):
        assert mention.disaster is Disaster.LANDSLIDE
        assert mention.role == "historical"
        assert mention.time and mention.time.start is None
        assert mention.time.wording == "last August"
        assert "11 October" not in mention.text
        assert "historical" in claim.qualifiers
        assert claim.excerpt in text
    current = [m for m in report.mentions if "overwhelmed the valley" in m.text]
    assert current
    assert all(m.disaster is Disaster.FLOOD for m in current)
    assert all(not m.claims for m in current)
    assert all(m.time and m.time.start.day == 11 for m in current)
    assert all(
        any("earlier occurrence" in n.lower() for n in m.notices) for m in current
    )


@pytest.mark.parametrize("earlier", ["last August", "last year", "previous winter"])
def test_two_explicit_physical_occurrences_keep_their_own_tolls(earlier):
    text = (
        f"After a flood killed three people in Oldtown {earlier}, "
        "yesterday, 11 October, another flood struck Brookside and killed two people."
    )
    report = assess(text)
    tolls = fatalities(report)
    assert len(tolls) == 2
    historical = [(m, c) for m, c in tolls if m.role == "historical"]
    current = [(m, c) for m, c in tolls if m.role == "reported"]
    assert len(historical) == len(current) == 1
    old, old_claim = historical[0]
    new, new_claim = current[0]
    assert old_claim.fact.value == "three"
    assert old.time.wording == earlier and old.time.start is None
    assert old.place.wording == "Oldtown"
    assert new_claim.fact.value == "two"
    assert new.time.start == datetime(2026, 10, 11, tzinfo=UTC)
    assert new.place.wording == "Brookside"
    assert "historical" not in new_claim.qualifiers
    assert all(c.excerpt in text for _, c in tolls)


def test_current_article_metadata_cannot_locate_or_date_the_earlier_account():
    text = (
        "After a landslide killed three people last August, today a flood "
        "struck Brookside and damaged homes."
    )
    geometry = point_event_geometry(10, 20, SOURCE)
    clock = datetime(2026, 10, 11, tzinfo=UTC)
    report = assess(text, location="Brookside", event_time=clock, geometry=geometry)
    assert report.article.geometry == geometry and report.article.event_time == clock
    assert fatalities(report)
    for mention, _ in fatalities(report):
        assert mention.place is None
        assert mention.geometry is None
        assert mention.country_context is None
        assert mention.time.wording == "last August" and mention.time.start is None


def test_a_calendar_day_in_the_relative_earlier_account_cannot_guess_this_year():
    text = (
        "After a flood killed three people on 11 October last year, "
        "yesterday another flood struck Brookside and killed two people."
    )
    report = assess(text)
    old = [(m, c) for m, c in fatalities(report) if m.role == "historical"]
    assert old
    assert all(m.time and m.time.start is None for m, _ in old)
    assert all(m.time.wording == "11 October last year" for m, _ in old)


@pytest.mark.parametrize(
    "later",
    [
        "today rescuers recovered two bodies from the same flood",
        "yesterday officials said the flood had killed three people",
        "yesterday officials said the flood struck last August",
        "today the flood response teams arrived",
    ],
)
def test_later_recovery_statement_or_response_is_not_a_new_physical_occurrence(later):
    text = f"After the flood struck last August, {later}."
    report = assess(text)
    assert report.mentions
    assert not any(
        "earlier occurrence" in notice.lower()
        for mention in report.mentions
        for notice in mention.notices
    )
    assert report.article.text == text


def test_current_deaths_after_rescuers_arrive_are_not_reclassified_as_historical():
    text = (
        "After rescuers arrived yesterday, a flood struck Brookside "
        "and killed two people."
    )
    report = assess(text)
    assert fatalities(report)
    assert all(m.role != "historical" for m, _ in fatalities(report))


def test_an_earlier_place_does_not_leak_into_the_later_unlocated_flood():
    text = (
        "After a flood killed three people in Oldtown last August, "
        "today another flood struck and killed two people."
    )
    report = assess(text)
    current = [(m, c) for m, c in fatalities(report) if m.role == "reported"]
    assert current
    assert all(c.fact.value == "two" and m.place is None for m, c in current)
