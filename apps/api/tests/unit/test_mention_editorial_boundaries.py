"""Editorial recommendation headings end report evidence, including retained text."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

NOW = datetime(2026, 10, 19, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Floods in Lakeview", "https://news.example/report", NOW, None, NOW
)


@pytest.mark.parametrize(
    "heading",
    [
        "Related News:",
        "Related stories",
        "RELATED ARTICLES",
        "Related content:",
        "## Related News",
        "## Related topics",
    ],
)
def test_recommendation_headings_end_narrative_before_other_hazard_accounts(heading):
    text = (
        "Floods struck Lakeview. Two people died.\n"
        f"{heading}\nEarthquake in Otherland leaves nine dead."
    )
    mentions = extract_mentions(text, SOURCE)
    assert len(mentions) == 1
    assert "Otherland" not in mentions[0].text
    assert {c.fact.value for c in mentions[0].claims} == {"Two"}


def test_ordinary_sentence_about_related_news_does_not_end_reported_evidence():
    mentions = extract_mentions(
        "Floods struck Lakeview. Officials discussed related news about the floods. "
        "Two people died.",
        SOURCE,
    )
    assert any(c.fact.value == "Two" for m in mentions for c in m.claims)


def test_plain_approximate_count_is_not_treated_as_an_about_section_heading():
    mentions = extract_mentions(
        "Floods struck Lakeview. About four people were killed.", SOURCE
    )
    assert any(c.fact.value == "four" for m in mentions for c in m.claims)


@pytest.mark.parametrize("heading", ["Related News:", "## Related topics"])
def test_headline_only_fallback_cannot_reintroduce_recommendation_casualties(heading):
    mentions = extract_mentions(
        "No further details have been published.\n"
        f"{heading}\nNine people died in Otherland.",
        SOURCE,
    )
    assert mentions
    assert all("Otherland" not in m.text and not m.claims for m in mentions)


def test_joint_episode_accounts_also_stop_at_the_editorial_boundary():
    mentions = extract_mentions(
        "Date of event\n2026-10-10\n\nFloods and landslides struck Lakeview.\n\n"
        "Two people died.\n\nRelated News:\n\nNine people died in Otherland.",
        replace(SOURCE, title="Lakeview flood and landslide report"),
    )
    accounts = [m.episode_account for m in mentions if m.episode_account]
    assert accounts
    assert all("Otherland" not in account.excerpt for account in accounts)
    assert {c.fact.value for account in accounts for c in account.claims} == {"Two"}
