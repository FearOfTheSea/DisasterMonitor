"""Keep vague toll wording and the population governed by a casualty predicate."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Source", "https://daily.example/report", NOW, None, NOW
)


def fatalities(text):
    return [
        claim
        for claim in extract_reported_impacts(text, SOURCE)
        if claim.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "number",
    [
        "hundreds of thousands",
        "tens of thousands",
        "tens of millions",
        "scores",
        "millions",
        "dozens",
        "hundreds",
    ],
)
@pytest.mark.parametrize(
    "template", ["The flood killed {} people.", "{} people died in the flood."]
)
def test_approximate_toll_preserves_the_whole_source_expression(number, template):
    text = template.format(number)
    (claim,) = fatalities(text)
    assert claim.fact.value == number
    assert claim.excerpt == text
    assert "approximate" in claim.qualifiers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The flood killed 27 girls and counselors.", "27"),
        ("27 girls and counselors died in the flood.", "27"),
        ("The flood killed three boys.", "three"),
        ("Two of the five people died in the flood.", "Two"),
        ("The flood killed two of the five campers.", "two"),
        ("Hundreds of thousands of people died in the flood.", "Hundreds of thousands"),
        ("The flood killed hundreds of thousands of people.", "hundreds of thousands"),
    ],
)
def test_one_toll_can_govern_a_group_or_subset(text, expected):
    (claim,) = fatalities(text)
    assert claim.fact.value == expected


@pytest.mark.parametrize(
    "text",
    [
        "25 girls and two counselors died in the flood.",
        "The flood killed 25 girls and two counselors.",
        "Hundreds of people and two counselors died in the flood.",
    ],
)
def test_separately_counted_groups_are_not_added_or_replaced_by_one_group(text):
    (claim,) = fatalities(text)
    assert claim.fact.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers


@pytest.mark.parametrize(
    "text",
    [
        "The drought killed hundreds of thousands of cattle.",
        "The wildfire killed hundreds of animals.",
        "Tens of thousands of livestock died in the drought.",
    ],
)
def test_approximate_animal_losses_are_not_human_fatalities(text):
    assert fatalities(text) == []


def test_mixed_animal_and_human_tolls_keep_unresolved_scope():
    (claim,) = fatalities("The flood killed hundreds of animals and two people.")
    assert claim.fact.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers


def test_approximate_toll_does_not_qualify_an_exact_injury_count():
    claims = extract_reported_impacts(
        "Hundreds of thousands of people died in the flood "
        "and two people were injured.",
        SOURCE,
    )
    by_category = {claim.fact.category: claim for claim in claims}
    assert by_category["fatalities"].fact.value == "Hundreds of thousands"
    assert "approximate" in by_category["fatalities"].qualifiers
    assert by_category["injuries"].fact.value == "two"
    assert "approximate" not in by_category["injuries"].qualifiers
    assert "uncertain" not in by_category["injuries"].qualifiers
