"""Weekday clocks require occurrence evidence and keep their reference explicit."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

SOURCE = SourceReference(
    "news",
    "Daily",
    "Regional flood update",
    "https://news.example/flood",
    datetime(2026, 10, 19, 15, tzinfo=UTC),
    None,
    datetime(2026, 10, 19, 18, tzinfo=UTC),
)


def test_explicit_past_weekday_attaches_to_the_same_local_occurrence():
    mentions = extract_mentions(
        "Flooding in and around Lakeview killed two people. "
        "Wednesday's historic rainfall caused flash flooding. "
        "In Lakeview, six people have died. By Thursday, three deaths were reported.",
        SOURCE,
    )
    physical = [m for m in mentions if m.role == "reported"]
    assert len(physical) == 1
    event = physical[0]
    assert event.place.wording == "Lakeview"
    assert event.time.start == datetime(2026, 10, 14, tzinfo=UTC)
    assert event.time.wording == "Wednesday"
    assert any("publication" in n and "weekday" in n for n in event.notices)
    assert all(m.time is None or m.time.start.day != 15 for m in mentions)


@pytest.mark.parametrize("clock", ["4 p.m.", "8 a.m."])
def test_time_abbreviation_before_weekday_keeps_the_physical_occurrence_clock(clock):
    (mention,) = extract_mentions(
        f"A grass fire ignited around {clock} Saturday at North Plains Base.",
        SOURCE,
    )
    assert mention.time and mention.time.start == datetime(2026, 10, 17, tzinfo=UTC)


@pytest.mark.parametrize("clock", ["4 p.m.", "8 a.m."])
def test_time_abbreviation_does_not_turn_a_statement_weekday_into_onset(clock):
    (mention,) = extract_mentions(
        f"A grass fire killed four soldiers, officials said around {clock} Saturday.",
        SOURCE,
    )
    assert mention.time is None


@pytest.mark.parametrize(
    "text",
    [
        "By Thursday, floods had killed three people in Lakeview.",
        "The flood response arrived in Lakeview on Wednesday.",
        "Floods may hit Lakeview on Friday.",
        "Floods will hit Lakeview on Friday.",
    ],
)
def test_update_activity_and_forecast_weekdays_do_not_become_onset(text):
    assert all(m.time is None for m in extract_mentions(text, SOURCE))


def test_weekday_without_publication_reference_is_preserved_without_inventing_a_date():
    source = replace(SOURCE, published_at=None, publication_precision="unknown")
    (mention,) = extract_mentions("Floods hit Lakeview on Wednesday.", source)
    assert mention.time.wording == "Wednesday"
    assert mention.time.start is None


def test_legacy_photo_caption_date_cannot_establish_occurrence_onset():
    mentions = extract_mentions(
        "Local residents walk through debris after floods caused by heavy rains "
        "in Lakeview, 15 October, 2026 AP Photo.",
        SOURCE,
    )
    assert all(m.time is None for m in mentions)


def test_dated_first_occurrence_without_a_place_remains_unlocated():
    (mention,) = extract_mentions("Floods occurred on Wednesday.", SOURCE)
    assert mention.place is None
    assert mention.time.start.day == 14


def test_last_week_uses_the_previous_calendar_week_instead_of_latest_weekday():
    source = replace(SOURCE, published_at=datetime(2026, 10, 18, tzinfo=UTC))
    (mention,) = extract_mentions("Floods hit Lakeview on Wednesday last week.", source)
    assert mention.time.start == datetime(2026, 10, 7, tzinfo=UTC)


def test_recordkeeping_baseline_does_not_reclassify_current_occurrence_as_historical():
    (mention,) = extract_mentions(
        "Wednesday's rainfall, which officials said was the heaviest since "
        "records began in 1942, caused flash flooding in Lakeview.",
        SOURCE,
    )
    assert mention.role == "reported"
    assert mention.time.start == datetime(2026, 10, 14, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    [
        "Four people died fighting a wildfire in Lakeview, officials said Friday.",
        "Floods killed two people in Lakeview, the mayor said on Friday.",
        "A landslide killed two in Lakeview, police told reporters on Friday.",
        "On Friday, officials said a wildfire killed four people in Lakeview.",
        "Floods killed two people in Lakeview, officials confirmed on 16 October.",
    ],
)
def test_statement_date_does_not_establish_occurrence_onset(text):
    mentions = extract_mentions(text, SOURCE)
    assert mentions
    assert all(m.time is None for m in mentions)


@pytest.mark.parametrize(
    "text",
    [
        "Floods hit Lakeview on Wednesday, officials said Friday.",
        "Officials said Friday that floods hit Lakeview on Wednesday.",
        "On Friday, officials said floods hit Lakeview on Wednesday.",
        "Officials said floods hit Lakeview on Wednesday.",
        "Officials said Wednesday's floods killed two people in Lakeview.",
        "Officials said: 'On Wednesday, floods hit Lakeview.'",
    ],
)
def test_occurrence_date_survives_a_different_statement_date(text):
    (mention,) = extract_mentions(text, SOURCE)
    assert mention.time.start == datetime(2026, 10, 14, tzinfo=UTC)
    assert mention.time.wording == "Wednesday"
