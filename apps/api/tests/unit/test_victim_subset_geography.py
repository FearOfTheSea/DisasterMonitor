"""One victim's locality does not locate a larger source casualty account."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.events import point_event_geometry
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def assess(text, title="Regional situation report", **metadata):
    source = SourceReference(
        "news", "Daily", title, "https://daily.example/report", NOW, None, NOW
    )
    return assess_article(
        DiscoveryArticle(source, text, **metadata), ReportingInterval.at_start(1, NOW)
    )


def tolls(result):
    return [
        (m, c)
        for m in result.mentions
        for c in m.claims
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "subset",
    [
        "one of them a boy who was electrocuted in Brookside",
        "one of the victims a worker buried in Brookside",
        "including a child who drowned in Brookside",
    ],
)
@pytest.mark.parametrize("title", ["Regional situation report", "Floods in Brookside"])
def test_a_total_cannot_take_its_location_from_only_a_victim_subset(subset, title):
    text = f"Two people died in the floods, {subset}."
    result = assess(text, title)
    assert result.article.text == text
    assert tolls(result)
    for mention, claim in tolls(result):
        assert mention.place is None
        assert claim.fact.reported_location is None
        assert claim.fact.value == "Two"
        assert claim.excerpt == text
        assert any("subset" in n for n in mention.notices)


def test_an_earlier_local_mention_cannot_lend_its_place_to_the_larger_toll():
    text = (
        "Flooding damaged homes in Brookside. "
        "Two people died in the floods, one of them a boy in Brookside."
    )
    result = assess(text)
    assert tolls(result)
    assert all(m.place is None for m, _ in tolls(result))


def test_raw_article_location_and_point_cannot_reappear_as_the_whole_toll_location():
    text = "Two people died in floods, one of them a worker in Brookside."
    source = assess(text).article.source
    geometry = point_event_geometry(10, 20, source)
    result = assess(
        text, "Floods in Brookside", location="Brookside", geometry=geometry
    )
    assert result.article.geometry == geometry
    assert result.article.location == "Brookside"
    assert tolls(result)
    assert all(m.geometry is None for m, _ in tolls(result))
    events = group_reports((result,))
    assert events
    assert all(e.geometry is None and e.location != "Brookside" for e in events)


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Two people died in floods across Westland, "
            "one of them a boy in Brookside.",
            "Westland",
        ),
        (
            "Floods in Brookside killed two people, one of them a visiting worker.",
            "Brookside",
        ),
        (
            "Two people died in floods in Brookside, including a worker from Westland.",
            "Brookside",
        ),
        (
            "One person died in the floods, one of the victims in Brookside.",
            "Brookside",
        ),
        ("Floods killed one person in Brookside.", "Brookside"),
        ("Floods damaged two homes, including a house in Brookside.", "Brookside"),
    ],
)
def test_explicit_whole_account_places_and_noncasualty_context_remain(text, expected):
    result = assess(text)
    assert any(m.place and m.place.wording == expected for m in result.mentions)
    assert result.article.text == text
