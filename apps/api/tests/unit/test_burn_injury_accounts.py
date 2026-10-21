"""Personal burn accounts retain their subtype and do not become injury totals."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

SOURCE = SourceReference(
    "news",
    "Daily",
    "Wildfire response",
    "https://daily.example/fire",
    datetime(2026, 10, 16, tzinfo=UTC),
    None,
    datetime(2026, 10, 17, tzinfo=UTC),
)


@pytest.mark.parametrize(
    ("sentence", "value"),
    [
        ("Two others suffered severe burns during the wildfire.", "Two"),
        ("Three firefighters sustained burns in the wildfire.", "Three"),
        ("No responders suffered burns during the wildfire.", "0"),
        (
            "Firefighters suffered severe burns during the wildfire.",
            "Reported; count unknown",
        ),
    ],
)
def test_personal_burn_accounts_keep_subtype_and_source(sentence, value):
    (claim,) = extract_reported_impacts(sentence, SOURCE, location="National park")
    assert claim.fact.category == "injuries"
    assert claim.fact.label == "Burn injuries"
    assert claim.fact.value == value
    assert claim.fact.source == SOURCE
    assert claim.fact.reported_location == "National park"
    assert claim.excerpt == sentence


@pytest.mark.parametrize(
    "sentence",
    [
        "Two houses suffered severe burns during the wildfire.",
        "Two hectares burned during the wildfire.",
        "Two responders did not suffer burns during the wildfire.",
        "Two firefighters may suffer burns if the wildfire spreads.",
        "Doctors warned two volunteers about severe burns.",
        "Two firefighters treated residents with burns.",
        "The wildfire burned three fire trucks and two houses.",
        "Two responders suffered equipment damage during the wildfire.",
    ],
)
def test_burn_mentions_without_actual_personal_casualties_are_not_injuries(sentence):
    assert not extract_reported_impacts(sentence, SOURCE)


def test_burn_subtype_is_separate_from_other_injury_accounts_without_summing():
    claims = extract_reported_impacts(
        "Three people were injured and two others suffered severe burns.",
        SOURCE,
    )
    assert [(claim.fact.label, claim.fact.value) for claim in claims] == [
        ("Injuries", "Three"),
        ("Burn injuries", "two"),
    ]


def test_zero_burns_does_not_erase_other_injuries():
    claims = extract_reported_impacts(
        "Three people were injured. No responders suffered burns.",
        SOURCE,
    )
    assert [(claim.fact.label, claim.fact.value) for claim in claims] == [
        ("Injuries", "Three"),
        ("Burn injuries", "0"),
    ]


def test_burn_account_keeps_casualty_event_date_and_place():
    from disaster_monitor.domain.discovery import (
        DiscoveryArticle,
        ReportingInterval,
        assess_article,
        group_reports,
    )

    report = assess_article(
        DiscoveryArticle(
            SOURCE,
            "Four people died and two others suffered severe burns while "
            "battling a wildfire in North Reserve, officials said Friday. "
            "The victims were among a team trying to contain the wildfire "
            "on Thursday.",
        ),
        ReportingInterval.at_start(30, SOURCE.retrieved_at),
    )
    (event,) = [
        event
        for event in group_reports((report,))
        if any(item.mention.claims for item in event.reports)
    ]
    assert event.event_time == datetime(2026, 10, 15, tzinfo=UTC)
    assert event.location == "North Reserve"
    claims = [claim for item in event.reports for claim in item.mention.claims]
    assert [(claim.fact.label, claim.fact.value) for claim in claims] == [
        ("Fatalities", "Four"),
        ("Burn injuries", "two"),
    ]
    assert all(claim.fact.reported_location == "North Reserve" for claim in claims)
