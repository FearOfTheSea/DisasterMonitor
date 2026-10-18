"""Physical mentions and evidence boundaries with invented fixture places."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def report(text, title="Regional situation update", url="https://news.example/one"):
    return DiscoveryArticle(
        SourceReference("news", "Daily", title, url, NOW, None, NOW), text
    )


def events(*articles):
    return group_reports(
        tuple(assess_article(a, ReportingInterval.at_start(7, NOW)) for a in articles)
    )


def test_one_article_has_separate_hazards_places_and_scoped_accounts():
    groups = events(
        report(
            "On 9 October 2026 an earthquake struck Riverton. Two people died. "
            "On 11 October 2026 floods hit Lakeview. Five people died."
        )
    )
    assert len(groups) == 2
    quake, flood = groups
    assert quake.location == "Riverton"
    assert flood.location == "Lakeview"
    assert "Five people died" not in quake.reports[0].mention.text
    assert "Two people died" not in flood.reports[0].mention.text
    assert quake.event_time.day == 9
    assert quake.reports[0].mention.time.precision == "day"


def test_updates_merge_by_specific_place_and_reported_day_but_nearby_events_do_not():
    first = report("On 9 October 2026 an earthquake struck Riverton. Two people died.")
    update = report(
        "The earthquake in Riverton on 9 October 2026 injured three people.",
        url="https://news.example/two",
    )
    other = report(
        "On 9 October 2026 an earthquake struck Lakeview.",
        url="https://news.example/three",
    )
    later = report(
        "On 12 October 2026 an earthquake struck Riverton.",
        url="https://news.example/four",
    )
    groups = events(first, update, other, later)
    assert len(groups) == 3
    assert len(groups[0].reports) == 2
    assert groups[0].association_reasons
    assert groups[0].event_id == events(first)[0].event_id


def test_same_hazard_two_places_and_historical_context_are_not_one_occurrence():
    groups = events(
        report(
            "On 11 October 2026 floods hit Lakeview. Two people died. "
            "In 2020 floods hit Riverton. Ten people died."
        )
    )
    assert len(groups) == 2
    assert groups[1].reports[0].mention.role == "historical"
    assert groups[1].event_time is None  # a year is not an exact onset


def test_country_and_unknown_onset_do_not_merge_and_no_publication_onset_fallback():
    one = report("Floods affected the country.", title="Flood situation")
    two = replace(
        one, source=replace(one.source, canonical_url="https://news.example/two")
    )
    groups = events(one, two)
    assert len(groups) == 2
    assert all(g.event_time is None and g.geometry is None for g in groups)
    assert all(g.identity_status == "candidate" for g in groups)


def test_compound_sentence_keeps_unallocated_deaths_out_of_each_hazard():
    groups = events(report("Floods and landslides in Riverton killed five people."))
    assert len(groups) == 2
    assert all(not g.reports[0].mention.claims for g in groups)
    assert all(g.reports[0].mention.notices for g in groups)


@pytest.mark.parametrize("days", [1, 3, 7, 14, 30])
def test_date_only_publication_requires_the_whole_day_inside_window(days):
    interval = ReportingInterval.at_start(days, NOW)
    article = report("Floods hit Riverton.")
    for date, expected in (
        (interval.start.replace(hour=0), "uncertain_publication"),
        (NOW.replace(hour=0), "uncertain_publication"),
        (
            (NOW - timedelta(days=1)).replace(hour=0),
            "eligible" if days > 1 else "uncertain_publication",
        ),
        ((interval.start - timedelta(days=1)).replace(hour=0), "outside_interval"),
    ):
        assessed = assess_article(
            replace(
                article,
                source=replace(
                    article.source, published_at=date, publication_precision="day"
                ),
            ),
            interval,
        )
        assert assessed.eligibility == expected


def test_date_only_overlap_stays_inspectable_as_candidate():
    article = report("On 9 October 2026 floods hit Riverton.")
    article = replace(
        article,
        source=replace(
            article.source,
            published_at=NOW.replace(hour=0),
            publication_precision="day",
        ),
    )
    groups = events(article)
    assert len(groups) == 1
    assert groups[0].identity_status == "candidate"


def test_section_headings_and_related_links_do_not_create_extra_physical_mentions():
    groups = events(
        report(
            "## Hurricane Arlen response\nHurricane Arlen is expected to hit Riverton. "
            "Preparations continue.\n## Flood recovery\n"
            "Floods struck Lakeview. Two people died.\n"
            "## In the News\nWildfire in Hilltown.\nHurricane Prep Pack"
        )
    )
    assert len(groups) == 2
    assert groups[0].reports[0].mention.name == "Arlen"
    assert groups[0].reports[0].mention.role == "forecast"
    assert all(g.disaster.value != "wildfire" for g in groups)


def test_medical_activity_does_not_establish_disaster_onset_or_casualties():
    groups = events(
        report(
            "On October 5 a doctor treated 49 patients for infections, injuries, "
            "chronic conditions including diabetes and hypertension, and distress "
            "among people affected by the floods."
        )
    )
    assert len(groups) == 1
    mention = groups[0].reports[0].mention
    assert mention.time is None
    assert not mention.claims


def test_dateline_and_occurrence_dates_are_not_silently_collapsed_to_one_onset():
    groups = events(
        report("RIVERTON, 11 October 2026 – Floods hit Riverton on 9 October 2026.")
    )
    assert groups[0].event_time == datetime(2026, 10, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    "month",
    [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ],
)
def test_calendar_month_is_not_an_affected_place(month):
    groups = events(report(f"Floods continued in {month}."))
    assert groups[0].reports[0].mention.place is None


@pytest.mark.parametrize(
    "identifier",
    [
        "glide:FL-2026-001",
        "sequence:storm-family",
        "earthquake-sequence:regional",
        "parent:broad",
    ],
)
def test_shared_context_identifier_does_not_establish_a_physical_occurrence(identifier):
    one = replace(
        report("Floods affected the country.", title="Flood update"),
        event_key=identifier,
        location="Country",
    )
    two = replace(
        one, source=replace(one.source, canonical_url="https://news.example/two")
    )
    grouped = events(one, two)
    assert len(grouped) == 2
    assert all(event.identity_status == "candidate" for event in grouped)
