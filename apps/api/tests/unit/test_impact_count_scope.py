"""A sentence with several casualty populations cannot supply one event total."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

SOURCE = SourceReference(
    "news",
    "Daily",
    "Disaster report",
    "https://daily.example/report",
    datetime(2026, 10, 24, tzinfo=UTC),
    None,
    datetime(2026, 10, 24, tzinfo=UTC),
)


@pytest.mark.parametrize(
    "text",
    [
        "In 2014 an avalanche killed 16 people, and in 2015 an earthquake "
        "killed 18 people, also on Everest.",
        "Two people died in the flood and three people died in the earthquake.",
        "Officials first reported two deaths but later reported three deaths.",
        "The wildfire killed three soldiers and a reservist.",
        "Three soldiers and a reservist died in the wildfire.",
        "The flood killed 25 youth campers, two counselors and the camp owner.",
        "Two workers plus three residents were killed in the landslide.",
    ],
)
def test_separate_counts_and_coordinated_populations_remain_unallocated(text):
    (claim,) = [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]
    assert claim.fact.value == "Unknown"
    assert {"uncertain", "scope unresolved"} <= set(claim.qualifiers)
    assert claim.excerpt == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The flood killed three people and injured 16 others.", "three"),
        ("Three people died while two workers cleared roads.", "Three"),
        ("The flood killed three people, including two children.", "three"),
        ("The flood killed three people; officials confirmed 3 deaths.", "3"),
        ("Three people died; another 20 were displaced.", "Three"),
        ("The flood killed three soldiers who rescued a reservist.", "three"),
        ("Three people died while two workers and a guard cleared roads.", "Three"),
    ],
)
def test_other_impacts_subsets_and_repeated_counts_do_not_hide_one_toll(text, expected):
    (claim,) = [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]
    assert claim.fact.value == expected
    assert "scope unresolved" not in claim.qualifiers


def test_an_earthquake_mention_cannot_take_the_preceding_avalanches_count():
    from disaster_monitor.domain.disaster_types import Disaster
    from disaster_monitor.domain.mention_extraction import extract_mentions

    text = (
        "In 2014 an avalanche killed 16 people on the mountain, "
        "and in 2015 an earthquake killed 18 people on the same mountain."
    )
    claims = [
        claim
        for mention in extract_mentions(text, SOURCE)
        if mention.disaster == Disaster.EARTHQUAKE
        for claim in mention.claims
        if claim.fact.category == "fatalities"
    ]
    assert claims
    assert all(claim.fact.value == "Unknown" for claim in claims)
    assert all("scope unresolved" in claim.qualifiers for claim in claims)
    assert all(claim.excerpt == text for claim in claims)
