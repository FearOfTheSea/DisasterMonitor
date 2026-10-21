"""Occurrence dates can support listed affected places without moving impacts."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

SOURCE = SourceReference(
    "news",
    "Daily",
    "Flood update",
    "https://news.example/report",
    datetime(2026, 10, 18, tzinfo=UTC),
    None,
    datetime(2026, 10, 18, tzinfo=UTC),
)


def test_unique_dated_occurrence_supports_explicitly_listed_local_impact_account():
    mentions = extract_mentions(
        "The reported figure refers to people rescued due to flooding in Lakeview. "
        "On 9 October 2026, rainfall caused flooding across Exampleland. "
        "The affected areas include Lakeview, Riverton and Harbor City. "
        "Reported incidents included flooding of roads and stranded people. "
        "In Lakeview, two fatalities were reported. "
        "According to forecasts, flooding is expected in Lakeview on 12 October.",
        SOURCE,
        location="Exampleland",
    )
    local = next(m for m in mentions if m.claims)
    assert local.place.wording == "Lakeview"
    assert local.time.start == datetime(2026, 10, 9, tzinfo=UTC)
    assert local.time.wording == "9 October 2026"
    assert local.claims[0].fact.value == "two"
    assert (
        "two fatalities"
        not in next(m for m in mentions if m.place.wording == "Exampleland").text
    )
    assert any("affected areas include Lakeview" in n for n in local.notices)
    assert all(m.time is None for m in mentions if m.role == "forecast")


@pytest.mark.parametrize(
    ("extra", "expected_day"),
    [
        ("On 11 October 2026 flooding hit Lakeview.", 11),
        ("A separate flood hit Lakeview.", None),
    ],
)
def test_competing_occurrences_prevent_implicit_local_date_attachment(
    extra, expected_day
):
    mentions = extract_mentions(
        "Flooding hit Exampleland on 9 October 2026. "
        "The affected areas include Lakeview and Riverton. "
        + extra
        + " Flooding in Lakeview killed two people.",
        SOURCE,
        location="Exampleland",
    )
    local = next(m for m in mentions if m.claims)
    assert (local.time.start.day if local.time else None) == expected_day


@pytest.mark.parametrize(
    "listing",
    [
        "The teams are based in Lakeview.",
        "The affected areas include Lakeview Heights and Riverton.",
        "Forecasts warn that the affected areas include Lakeview and Riverton.",
    ],
)
def test_place_mentions_and_partial_name_matches_do_not_establish_membership(listing):
    mentions = extract_mentions(
        "Floods hit Exampleland on 9 October 2026. "
        + listing
        + " Flooding in Lakeview killed two people.",
        SOURCE,
        location="Exampleland",
    )
    local = next(m for m in mentions if m.claims)
    assert local.time is None


def test_national_claims_are_not_transferred_to_listed_localities():
    mentions = extract_mentions(
        "Floods hit Exampleland on 9 October 2026. "
        "The affected areas include Lakeview and Riverton. "
        "Across Exampleland, 50 people died. Flooding in Lakeview damaged roads.",
        SOURCE,
        location="Exampleland",
    )
    local = next(m for m in mentions if m.place and m.place.wording == "Lakeview")
    assert local.time.start.day == 9
    assert not any(c.fact.category == "fatalities" for c in local.claims)
    assert any(c.fact.value == "50" for m in mentions for c in m.claims)


def test_explicit_local_reentry_preserves_its_own_claims_after_regional_context():
    mentions = extract_mentions(
        "Floods hit Lakeview. Floods hit Exampleland on 9 October. "
        "In Lakeview, two fatalities were reported.",
        SOURCE,
        location="Exampleland",
    )
    local = next(m for m in mentions if m.place.wording == "Lakeview")
    assert local.claims[0].fact.value == "two"
    assert local.time is None  # No explicit affected-place membership.
    regional = next(m for m in mentions if m.place.wording == "Exampleland")
    assert not regional.claims


def test_local_reentry_cannot_choose_between_multiple_occurrences_in_one_place():
    mentions = extract_mentions(
        "Floods hit Lakeview on 9 October. Floods hit Lakeview on 11 October. "
        "Floods hit Exampleland. In Lakeview, two fatalities were reported.",
        SOURCE,
        location="Exampleland",
    )
    assert not any(m.claims for m in mentions if m.time)
