"""Extraction-only source excerpts; none of these URLs enters normal acquisition."""

from datetime import UTC, datetime

from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def test_panama_updates_share_occurrence_but_retain_article_identity():
    reports = []
    for number, node, text in (
        (
            "04",
            "4234127",
            "The 7.5-magnitude earthquake that struck on 9 October affected several "
            "provinces across the country, particularly Veraguas, Coclé, Herrera "
            "and Los Santos.",
        ),
        (
            "05",
            "4234493",
            "Following the magnitude 7.5 earthquake on 9 October, the National "
            "Civil Protection System (SINAPROC) reports 13,623 people affected, "
            "from 4,045 families.",
        ),
    ):
        source = SourceReference(
            "reliefweb-discovery",
            "UN Office for the Coordination of Humanitarian Affairs",
            f"Panama: Earthquake in Azuero & Veraguas - Situation Report No. {number}",
            f"https://reliefweb.int/node/{node}",
            NOW,
            None,
            NOW,
        )
        reports.append(
            assess_article(
                DiscoveryArticle(source, text, location="Panama"),
                ReportingInterval.at_start(30, NOW),
            )
        )
    events = group_reports(tuple(reports))
    assert len(events) == 1
    assert events[0].event_time.day == 9
    assert len(events[0].reports) == 2
    assert events[0].geometry is None


def test_collected_multihazard_reporting_recovers_both_named_storm_mentions():
    source = SourceReference(
        "reliefweb-discovery",
        "OCHA",
        "Latin America & The Caribbean Weekly Situation Update as of 12 October 2026",
        "https://reliefweb.int/node/4233704",
        NOW,
        None,
        NOW,
    )
    text = (
        "Hurricane Simon strengthened to Category 4 on 11 October but stayed "
        "offshore, moving north-west parallel to the coasts of Colima and Jalisco. "
        "In Guerrero, where Simon’s rains hit Acapulco earlier in the week, "
        "authorities reported one death, two injuries and 112 damaged homes. "
        "Meanwhile, Hurricane Isaias, the first Atlantic hurricane of the 2026 "
        "season, has moved away from Mexico towards the US coast after bringing "
        "rain and rough seas to the Yucatán Peninsula."
    )
    assessed = assess_article(
        DiscoveryArticle(source, text), ReportingInterval.at_start(30, NOW)
    )
    assert {m.name for m in assessed.mentions} == {"Simon", "Isaias"}
    simon, isaias = assessed.mentions
    assert any(c.fact.category == "fatalities" for c in simon.claims)
    assert not isaias.claims
