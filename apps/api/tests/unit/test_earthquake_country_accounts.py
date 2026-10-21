"""One source can describe an epicentre and a national account of the same quake."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 18, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Exampleland earthquake update",
    "https://news.example/quake",
    NOW,
    None,
    NOW,
)


def project(extra=""):
    article = DiscoveryArticle(
        SOURCE,
        "On 9 October 2026 a magnitude 7.4 earthquake struck Ridge Province. "
        + extra
        + "The earthquake was felt in Neighborland. "
        "According to the national authority, 331 people died.",
        location="Exampleland",
    )
    return group_reports(
        (
            assess_article(
                article,
                ReportingInterval.at_start(30, NOW),
                country_names=frozenset({"exampleland", "neighborland"}),
            ),
        )
    )


def test_national_account_links_to_unique_dated_magnitude_without_local_allocation():
    (event,) = project()
    assert event.location == "Exampleland"
    assert event.event_time == datetime(2026, 10, 9, tzinfo=UTC)
    assert event.identity_status == "associated"
    assert len(event.reports) == 2
    assert event.reports[0].mention_count == 1
    root, national = (r.mention for r in event.reports)
    assert root.place.wording == "Ridge Province"
    assert not root.claims
    assert national.place.wording == "Exampleland"
    assert national.claims[0].fact.reported_location == "Exampleland"
    assert national.time == root.time
    assert national.occurrence_anchor_id == root.mention_id
    assert any("Same article" in reason for reason in event.association_reasons)


@pytest.mark.parametrize(
    "extra",
    [
        "On 11 October a magnitude 6.2 earthquake struck Lakeview. ",
        "A separate earthquake struck Lakeview. ",
        "An aftershock hit Lakeview. ",
    ],
)
def test_competing_earthquake_occurrences_keep_unallocated_national_account_separate(
    extra,
):
    events = project(extra)
    national = next(e for e in events if any(r.mention.claims for r in e.reports))
    assert len(national.reports) == 1
    assert national.event_time is None


def test_link_does_not_merge_another_article_by_country_and_day():
    event = project()[0]
    other = DiscoveryArticle(
        SourceReference(
            "news", "Other", SOURCE.title, "https://news.example/other", NOW, None, NOW
        ),
        "On 9 October 2026 a magnitude 7.4 earthquake struck Lakeview.",
        location="Exampleland",
    )
    reports = (
        *event.reports,
        assess_article(other, ReportingInterval.at_start(30, NOW)),
    )
    assert len(group_reports(reports)) == 2


def test_general_aftershock_sequence_does_not_become_an_individual_occurrence():
    (event,) = project(
        "The earthquake was followed by multiple aftershocks and was felt "
        "across much of the country. "
    )
    assert event.event_time.day == 9
    assert all(r.mention_count == 1 for r in event.reports)
    assert sum(len(r.mention.claims) for r in event.reports) == 1


def title_country_report(extra="", *, repeated_magnitude=True):
    title = "7.4-magnitude earthquake in Exampleland leaves one dead"
    article = DiscoveryArticle(
        replace(SOURCE, title=title),
        (title + "\n" if repeated_magnitude else "")
        + "Authorities said on Oct. 14 that one person injured in the earthquake "
        "had died. "
        + extra
        + "A magnitude-7.4 earthquake struck Exampleland on Oct. 9. "
        "Several aftershocks followed.",
    )
    return assess_article(
        article,
        ReportingInterval.at_start(30, NOW),
        country_names=frozenset({"exampleland", "otherland"}),
    )


@pytest.mark.parametrize("repeated_magnitude", [False, True])
def test_explicit_title_country_and_repeated_magnitude_link_to_one_dated_occurrence(
    repeated_magnitude,
):
    report = title_country_report(repeated_magnitude=repeated_magnitude)
    accounts = [m for m in report.mentions if m.claims]
    assert accounts
    assert all(
        m.time and m.time.start == datetime(2026, 10, 9, tzinfo=UTC) for m in accounts
    )
    assert all(m.country_context == "Exampleland" for m in accounts)
    assert all(m.place.precision == "country_context" for m in accounts)
    assert all(
        c.fact.reported_location == "Exampleland" for m in accounts for c in m.claims
    )
    assert len(group_reports((report,))) == 1
    assert any(m.occurrence_anchor_id for m in accounts)


@pytest.mark.parametrize(
    "extra",
    [
        "Another magnitude-7.4 earthquake struck Exampleland. ",
        "A separate magnitude-7.4 earthquake struck Exampleland. ",
        "A magnitude-6.2 earthquake also struck Exampleland. ",
        "An aftershock hit Exampleland. ",
        "On October 11 a magnitude-7.4 earthquake struck Exampleland. ",
    ],
)
def test_competing_undated_or_dated_quakes_still_block_same_magnitude_country_link(
    extra,
):
    report = title_country_report(extra)
    accounts = [m for m in report.mentions if m.claims]
    assert accounts
    assert all(m.occurrence_anchor_id is None for m in accounts)
