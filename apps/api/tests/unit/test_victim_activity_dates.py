"""A source's dated victim activity identifies the casualty incident, not ignition."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Wildfire in North Reserve",
    "https://news.example/fire",
    NOW,
    None,
    NOW,
)


def assess(activity, *, intervening="", country=None):
    return assess_article(
        DiscoveryArticle(
            SOURCE,
            "Four people died while battling a wildfire in North Reserve, "
            "officials said Friday. " + intervening + activity,
            location=country,
        ),
        ReportingInterval.at_start(30, NOW),
        country_names=frozenset({"exampleland", "otherland"}),
    )


@pytest.mark.parametrize(
    "activity",
    [
        "The victims were among a twelve-member firefighting team trying "
        "to contain the wildfire on Thursday.",
        "Officials said Friday that the victims were among a team "
        "battling the wildfire on Thursday.",
    ],
)
def test_dated_victim_firefighting_activity_links_the_casualty_incident(activity):
    report = assess(activity)
    (event,) = [
        e for e in group_reports((report,)) if any(r.mention.claims for r in e.reports)
    ]
    assert event.event_time == datetime(2026, 10, 15, tzinfo=UTC)
    assert event.location == "North Reserve"
    mention = next(m for m in report.mentions if m.claims)
    assert any(
        c.fact.category == "fatalities" and c.fact.value == "Four"
        for c in mention.claims
    )
    assert any("ignition" in notice for notice in mention.notices)


@pytest.mark.parametrize(
    "activity",
    [
        "The victims were treated on Thursday after fighting the wildfire.",
        "The victims were among a team preparing for a wildfire drill on Thursday.",
        "The victims will be among a team battling the wildfire on Thursday.",
        "The firefighters were among a team trying to contain the wildfire "
        "on Thursday.",
        "The victims were among a team fighting a factory fire on Thursday.",
        "The victims were among a team fighting floods and a wildfire on Thursday.",
    ],
)
def test_other_activity_or_ambiguous_hazard_does_not_date_the_casualty_incident(
    activity,
):
    report = assess(activity)
    casualty = next(m for m in report.mentions if m.claims)
    assert casualty.time is None


def test_victim_reference_does_not_borrow_an_intervening_locality_for_the_count():
    report = assess(
        "The victims were among a team trying to contain the wildfire on Thursday.",
        intervening="The blaze erupted in recent days in Lower Ridge. ",
    )
    (event,) = [
        e for e in group_reports((report,)) if any(r.mention.claims for r in e.reports)
    ]
    assert event.event_time == datetime(2026, 10, 15, tzinfo=UTC)
    casualty = next(m for m in report.mentions if m.claims)
    assert casualty.place.wording == "North Reserve"
    assert all(c.fact.reported_location == "North Reserve" for c in casualty.claims)
    assert any("ignition" in notice for notice in casualty.notices)


@pytest.mark.parametrize(
    "intervening",
    [
        "A house fire broke out in Lakeview. ",
        "Another wildfire struck Lakeview. ",
        "Floods struck Lakeview. ",
        "\n## Other reports\n",
        "Officials discussed training arrangements. " * 9,
    ],
)
def test_unresolved_victim_reference_cannot_date_an_earlier_casualty_account(
    intervening,
):
    report = assess(
        "The victims were among a team trying to contain the wildfire on Thursday.",
        intervening=intervening,
    )
    casualty = next(m for m in report.mentions if m.claims)
    assert casualty.time is None


def test_reporting_verb_cannot_reintroduce_a_date_after_an_unlinked_topic_break():
    report = assess(
        "The victims were among a team fighting the wildfire on Thursday, "
        "officials reported Friday.",
        intervening="\n## Other reports\n",
    )
    assert next(m for m in report.mentions if m.claims).time is None


def test_historical_victim_activity_does_not_date_current_casualties():
    report = assess(
        "The victims were among a team fighting the wildfire in 2019 on Thursday."
    )
    assert next(m for m in report.mentions if m.claims).time is None


def test_victim_reference_cannot_transfer_a_day_across_conflicting_known_countries():
    report = assess(
        "The victims were among a team fighting the wildfire in Otherland on Thursday.",
        country="Exampleland",
    )
    assert next(m for m in report.mentions if m.claims).time is None
