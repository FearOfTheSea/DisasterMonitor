"""Prospective quoted deaths remain source context, not observed fatal accounts."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 24, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Flood rescue", "https://daily.example/flood", NOW, None, NOW
)


@pytest.mark.parametrize(
    "text",
    [
        "“How many people are going to die?” he asked.",
        "I am going to die in this flood.",
        "He is going to be killed by the floodwater.",
        "Two people were going to die unless the boat reached them.",
        "Three people will die if nobody rescues them.",
        "People will be drowned if the bridge fails.",
        "Four people will be dead by morning if the river rises.",
    ],
)
def test_a_prediction_alone_does_not_assert_observed_deaths(text):
    assert not extract_reported_impacts(text, SOURCE)


def test_a_quoted_future_question_cannot_borrow_an_observed_floods_role():
    text = (
        "Floods struck Lakeview on 4 October 2025. "
        "“How many people are going to die?” he asked. "
        "The rescue boat reached the stranded families."
    )
    mentions = extract_mentions(text, SOURCE)
    assert mentions
    assert any("going to die" in m.text for m in mentions)
    assert not any(c.fact.category == "fatalities" for m in mentions for c in m.claims)


@pytest.mark.parametrize(
    "text",
    [
        "Three people died before he asked, “How many people are going to die?”",
        "Three people died but four others will be killed if the dam fails.",
    ],
)
def test_a_separate_observed_death_account_survives_a_future_prediction(text):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "Three"
    assert claim.excerpt == text
    assert claim.fact.source == SOURCE


@pytest.mark.parametrize(
    "text",
    [
        "Three people died in the flood.",
        "Three people may have died in the flood.",
        "Three people might have been killed in the flood.",
    ],
)
def test_past_reported_deaths_remain_distinct_from_predictions(text):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "Three"
    assert claim.excerpt == text
