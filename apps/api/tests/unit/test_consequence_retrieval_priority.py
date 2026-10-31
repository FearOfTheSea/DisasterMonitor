"""Inspect consequence reporting without inventing fatality claims from metadata."""

from dataclasses import replace

import pytest

from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.news import NewsFeedItem

LEAD = NewsFeedItem(
    "lead", "Local Daily", "Local update", "https://daily.example/update", None, None
)


@pytest.mark.parametrize(
    "headline",
    [
        "Flood survivors describe years in temporary homes",
        "Province issues disaster declaration after landslide",
        "Earthquake anniversary remembered at community gathering",
        "Wildfire memorial honors displaced families",
        "Volcanic eruption survivors discuss rehabilitation",
    ],
)
def test_consequence_headlines_receive_inspection_priority_without_death_metadata(
    headline,
):
    lead = replace(LEAD, title=headline)
    before = replace(lead)
    assert lead_retrieval_priority(lead) == 2
    assert lead == before
    assert lead.published_at is None


@pytest.mark.parametrize(
    "headline",
    [
        "City seeks disaster declaration ahead of forecast floods",
        "Anniversary drill simulates an earthquake",
        "Survivors of factory explosion move into new homes",
        "Memorial tributes flood in for beloved actor",
        "Families move after heavy rainfall",
        "No deaths reported as flood survivors await resettlement",
    ],
)
def test_forecasts_and_unrecognized_or_nonliteral_context_do_not_gain_priority(
    headline,
):
    assert lead_retrieval_priority(replace(LEAD, title=headline)) == 0


def test_native_search_title_retains_consequence_context():
    lead = replace(
        LEAD,
        search_title="Hurricane survivors return to damaged homes",
        discovery_hint="Copyright retained by publisher",
    )
    assert lead_retrieval_priority(lead) == 2


def test_direct_fatality_stays_ahead_of_consequence_and_weak_themes():
    death = replace(LEAD, title="Earthquake killed two people")
    consequence = replace(LEAD, title="Earthquake survivors await resettlement")
    weak = replace(LEAD, discovery_hint="earthquake; death-related index theme")
    assert lead_retrieval_priority(death) > lead_retrieval_priority(consequence)
    assert lead_retrieval_priority(consequence) > lead_retrieval_priority(weak)
