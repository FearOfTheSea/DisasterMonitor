"""A definite fire reference can identify one preceding physical grass fire."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Daily",
    "Fire during army training",
    "https://news.example/fire",
    NOW,
    None,
    NOW,
)


def report(*, extra="", reference="The fire", onset="", heading=""):
    return assess_article(
        DiscoveryArticle(
            SOURCE,
            "Four soldiers died when a grass fire swept through a military "
            f"training area in River Province{onset}. "
            "The soldiers were preparing for a deployment in Neighborland. "
            + extra
            + heading
            + f"{reference} ignited on Saturday inside a training area "
            "at North Plains Base.",
        ),
        ReportingInterval.at_start(30, NOW),
    )


def test_definite_fire_reference_links_onset_and_base_but_preserves_casualty_scope():
    assessed = report()
    (casualty,) = [m for m in assessed.mentions if m.claims]
    assert casualty.time and casualty.time.start == datetime(2026, 10, 17, tzinfo=UTC)
    assert casualty.place.wording == "River Province"
    assert casualty.claims[0].fact.reported_location == "River Province"
    assert casualty.occurrence_anchor_id
    (event,) = [
        e
        for e in group_reports((assessed,))
        if any(r.mention.claims for r in e.reports)
    ]
    assert event.location == "North Plains Base"
    assert event.event_time == datetime(2026, 10, 17, tzinfo=UTC)
    assert event.identity_status == "associated"
    assert len(event.reports) == 2
    assert any("Same article" in reason for reason in event.association_reasons)
    assert all("magnitude" not in reason for reason in event.association_reasons)


@pytest.mark.parametrize(
    "options",
    [
        {"reference": "A fire"},
        {"reference": "A separate fire"},
        {"reference": "The training drill fire"},
        {"onset": " on Friday"},
        {"extra": "Another wildfire struck Lakeview on Friday. "},
        {"extra": "A house fire broke out in Lakeview. "},
        {"extra": "A landslide hit Lakeview. "},
        {"heading": "\n## Other reports\n"},
        {"extra": "Officials discussed training arrangements. " * 9},
    ],
)
def test_competing_or_unlinked_fire_context_does_not_acquire_a_different_onset(options):
    assessed = report(**options)
    casualty = next(m for m in assessed.mentions if m.claims)
    assert casualty.occurrence_anchor_id is None
    assert not casualty.time or casualty.time.start == datetime(
        2026, 10, 16, tzinfo=UTC
    )
