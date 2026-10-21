"""A joint episode's casualties must never become each hazard's casualties."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

SOURCE = SourceReference(
    "news",
    "Public report",
    "Flood and landslide response",
    "https://reports.example/episode",
    datetime(2026, 10, 12, tzinfo=UTC),
    None,
    datetime(2026, 10, 13, tzinfo=UTC),
)
BODY = """Date of event
30-09-2026

A weather system brought floods and landslides in Riverton Province.

Further flooding and landslides are expected in the region.
Up to 100 people may be displaced.

An estimated 9,032 people were temporarily displaced across four townships.
A total of 25 deaths and 11 injuries were reported.

Floods and landslides damaged roads and bridges.
"""


@pytest.mark.parametrize("separator", ["\n", "\n\n", "\n\n\n"])
def test_combined_episode_keeps_one_shared_account_outside_hazard_claims(separator):
    mentions = extract_mentions(
        BODY.replace("Date of event\n", "Date of event" + separator), SOURCE
    )
    linked = [m for m in mentions if getattr(m, "episode_account", None)]
    assert {m.disaster for m in linked} == {Disaster.FLOOD, Disaster.LANDSLIDE}
    accounts = {m.episode_account.account_id: m.episode_account for m in linked}
    assert len(accounts) == 1
    account = next(iter(accounts.values()))
    assert account.hazards == (Disaster.FLOOD, Disaster.LANDSLIDE)
    assert account.place.wording == "Riverton Province"
    assert account.time.start == datetime(2026, 9, 30, tzinfo=UTC)
    assert {(c.fact.category, c.fact.value) for c in account.claims} >= {
        ("fatalities", "25"),
        ("injuries", "11"),
        ("displacement", "9032"),
    }
    assert all(c.fact.reported_location is None for c in account.claims)
    displaced = next(c for c in account.claims if c.fact.category == "displacement")
    assert {"uncertain", "temporary"} <= set(displaced.qualifiers)
    assert not any(c.fact.value == "100" for c in account.claims)
    assert not any("100" in c.excerpt for c in account.claims)
    assert all(not m.claims for m in linked)
    assert all(m.time == account.time for m in linked)


@pytest.mark.parametrize(
    "change",
    [
        "A separate flood hit Lakeview on 5 October, killing two people.",
        "An earthquake struck Riverton on 1 October, killing four people.",
        "Violence killed 20 people in the same area.",
        "A weather system brought floods and landslides in Lakeview Province.",
    ],
)
def test_competing_events_places_or_causes_prevent_a_report_wide_account(change):
    assert not any(
        getattr(m, "episode_account", None)
        for m in extract_mentions(BODY + change, SOURCE)
    )


@pytest.mark.parametrize(
    "date",
    [
        "04-05-2026",
        "31-02-2026",
        "30-11-2026",
        "",
        "30-09-2026\nDate of event\n01-10-2026",
    ],
)
def test_ambiguous_invalid_or_multiple_episode_date_fields_stay_unresolved(date):
    assert not any(
        getattr(m, "episode_account", None)
        for m in extract_mentions(BODY.replace("30-09-2026", date), SOURCE)
    )
