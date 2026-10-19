"""Occurrence evidence and clocks stay separate from preparation and response."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

SOURCE = SourceReference(
    "news",
    "Daily",
    "Regional update",
    "https://news.example/report",
    datetime(2026, 10, 18, tzinfo=UTC),
    None,
    datetime(2026, 10, 18, tzinfo=UTC),
)


def test_response_references_do_not_turn_a_clinician_base_into_an_event_location():
    mentions = extract_mentions(
        "Floods hit Riverton and Lakeview districts on 26 August. "
        "A physician based in Harbor City joined the response team. "
        "After the floods, the organization asked her to provide medical care. "
        "Aid was sent to partners responding in Exampleland's "
        "flood-affected districts.",
        SOURCE,
    )
    physical = [m for m in mentions if m.role in ("reported", "ongoing")]
    assert len(physical) == 1
    assert physical[0].place.wording == "Riverton and Lakeview districts"
    assert all(not m.place or m.place.wording != "Harbor City" for m in mentions)
    assert any("medical care" in m.text for m in mentions)
    assert any("Aid was sent" in m.text for m in mentions)


def test_undated_same_place_accounts_attach_to_the_unique_dated_article_anchor():
    mentions = extract_mentions(
        "In Lakeview district, patients struggled after floods cut off access. "
        "Floods swept through the region after a medical team reached "
        "Exampleland's Lakeview district. "
        "The Aug. 26 floods devastated communities, with Riverton and Lakeview "
        "among the hardest-hit districts. "
        "Roads and bridges were destroyed.",
        SOURCE,
    )
    physical = [m for m in mentions if m.role in ("reported", "ongoing")]
    assert len(physical) == 1
    assert physical[0].time.start.day == 26
    assert physical[0].place.wording == "Riverton and Lakeview"
    assert "patients struggled" in physical[0].text
    assert "Roads and bridges" in physical[0].text


def test_undated_other_places_and_multiple_dated_anchors_do_not_collapse():
    mentions = extract_mentions(
        "Floods hit Riverton on 26 August. Floods hit Lakeview on 28 August. "
        "Floods hit Harbor City. Floods hit Riverton.",
        SOURCE,
    )
    physical = [m for m in mentions if m.role in ("reported", "ongoing")]
    assert len(physical) == 4


def test_separate_undated_occurrence_is_not_joined_by_shared_response_words():
    mentions = extract_mentions(
        "Floods hit Riverton on 26 August. "
        "A separate flood hit Riverton and medical teams responded.",
        SOURCE,
    )
    assert len([m for m in mentions if m.role == "reported"]) == 2


def test_explicit_human_impact_in_a_response_account_still_establishes_occurrence():
    (mention,) = extract_mentions(
        "After floods in Riverton, medical teams reported that three people died.",
        SOURCE,
    )
    assert mention.role == "reported"
    assert mention.claims[0].fact.value == "three"


def test_response_continuity_does_not_allocate_combined_hazard_accounts():
    mentions = extract_mentions(
        "Floods hit Riverton on 26 August. "
        "Floods and landslides affected Riverton while medical teams responded.",
        SOURCE,
    )
    principal = next(m for m in mentions if m.time and m.time.start)
    assert "landslides" not in principal.text
    assert (
        len([m for m in mentions if any(n.startswith("Combined") for n in m.notices)])
        == 2
    )


@pytest.mark.parametrize("wording", ["Aug. 26", "Aug 26", "26 Aug.", "26 August"])
def test_abbreviated_month_periods_remain_part_of_reported_event_date(wording):
    mentions = extract_mentions(
        f"The {wording} floods devastated communities in Riverton. "
        "The response as of Oct. 2 included medical care.",
        SOURCE,
    )
    timed = [m for m in mentions if m.time and m.time.start]
    assert len(timed) == 1
    assert timed[0].time.start == datetime(2026, 8, 26, tzinfo=UTC)
    assert timed[0].time.wording == wording
    assert all(m.time is None or m.time.start.month != 10 for m in mentions)


def test_named_administrative_group_keeps_names_before_affected_descriptor():
    mentions = extract_mentions(
        "The Aug. 26 floods devastated northern Exampleland, with Riverton and "
        "Lakeview among the hardest-hit districts.",
        SOURCE,
    )
    assert len(mentions) == 1
    assert mentions[0].place.wording == "Riverton and Lakeview"
    assert mentions[0].place.role == "administrative_area"


def test_distinct_hazard_clauses_keep_their_own_descriptive_place():
    mentions = extract_mentions(
        "Authorities reported flooding in North Valley, as well as a M6.1 "
        "earthquake in South Island.",
        SOURCE,
    )
    assert {m.disaster.value: m.place.wording for m in mentions} == {
        "flood": "North Valley",
        "earthquake": "South Island",
    }
    assert all(not m.claims for m in mentions)


@pytest.mark.parametrize(
    "text",
    [
        "Officials are preparing for floods in Riverton.",
        "A simulation of an earthquake in Riverton tested emergency teams.",
        "Mandatory evacuations are in effect, with officials warning of flooding.",
        "We place emergency supplies ahead of hurricane season.",
    ],
)
def test_preparation_is_preserved_without_claiming_a_physical_occurrence(text):
    mentions = extract_mentions(text, SOURCE)
    assert mentions
    assert all(m.role == "forecast" for m in mentions)
    assert all(not m.claims and m.time is None for m in mentions)


def test_fragment_is_unresolved_and_does_not_inherit_heading_as_an_occurrence():
    mentions = extract_mentions(
        "## Flood response\nDr. Lin provided medical care.", SOURCE
    )
    assert len(mentions) == 1
    assert mentions[0].role == "uncertain"
    assert mentions[0].excerpt != "Dr."


def test_dateline_and_response_dates_do_not_obscure_explicit_occurrence_date():
    (mention,) = extract_mentions(
        "RIVERTON, 11 October 2026 – Floods hit Riverton on 9 October 2026. "
        "Teams arrived on 10 October and treated patients on 11 October.",
        SOURCE,
    )
    assert mention.time.start == datetime(2026, 10, 9, tzinfo=UTC)
    assert mention.time.wording == "9 October 2026"


@pytest.mark.parametrize(
    "activity", ["assessment", "response", "treatment", "publication"]
)
def test_activity_date_is_not_onset(activity):
    (mention,) = extract_mentions(
        f"Floods affected Riverton. The {activity} on 11 October 2026 continues.",
        SOURCE,
    )
    assert mention.time is None


def test_repeated_named_event_without_onset_is_one_mention_but_distinct_places_remain():
    mentions = extract_mentions(
        "Floods hit Riverton. Two people died. "
        "Floods hit Lakeview. Three people died. "
        "Flooding in Riverton damaged roads.",
        SOURCE,
    )
    assert len(mentions) == 2
    assert "damaged roads" in mentions[0].text
    assert "Three people died" not in mentions[0].text


def test_ongoing_and_historical_mentions_remain_distinct():
    ongoing, historical = extract_mentions(
        "Flooding continues in Riverton. In 2020 floods hit Lakeview.",
        SOURCE,
    )
    assert ongoing.role == "ongoing"
    assert historical.role == "historical"


def test_occurrence_range_is_retained_without_midpoint_or_publication_substitution():
    (mention,) = extract_mentions(
        "Floods hit Riverton from 9 to 11 October 2026.",
        SOURCE,
    )
    assert mention.time.precision == "range"
    assert mention.time.start.day == 9
    assert mention.time.end.day == 12


def test_followup_preparation_and_clinic_context_retain_one_occurred_event():
    mentions = extract_mentions(
        "## Flood-affected Riverton\nFloods hit Riverton on 9 October 2026. "
        "Teams are preparing for more rain. "
        "On October 12 a doctor treated 49 patients affected by the floods.",
        SOURCE,
    )
    assert len(mentions) == 1
    assert mentions[0].role == "reported"
    assert mentions[0].time.start.day == 9
    assert not any(c.fact.category == "injuries" for c in mentions[0].claims)


def test_administrative_list_and_occurrence_date_survive_dateline_and_risk_context():
    (mention,) = extract_mentions(
        "CAPITAL, 11 October 2026 – Flash floods tore through Rasuwa, Nuwakot "
        "and Dhading districts on 9 October. Children now face risks of disease.",
        SOURCE,
    )
    assert mention.time.start.day == 9
    assert mention.place.wording == "Rasuwa, Nuwakot and Dhading districts"
    assert mention.role == "reported"


def test_approximate_wording_and_reporting_clock_remain_distinct():
    (mention,) = extract_mentions("Floods hit Riverton in early October.", SOURCE)
    assert mention.time.wording == "early October"
    assert mention.time.start is None
    (reported,) = extract_mentions(
        "Authorities reported on 11 October 2026 that floods hit Riverton.",
        SOURCE,
    )
    assert reported.time is None


def test_claim_in_another_place_without_event_link_remains_unresolved():
    first, context = extract_mentions(
        "Floods hit Riverton on 9 October. In Lakeview three people died.",
        SOURCE,
    )
    assert not first.claims
    assert context.role == "uncertain"
    assert context.place.wording == "Lakeview"
    assert not context.claims


def test_storm_intensity_update_does_not_establish_impact_onset():
    (mention,) = extract_mentions(
        "Hurricane Arlen strengthened on 9 October 2026.", SOURCE
    )
    assert mention.role == "reported"
    assert mention.time is None or mention.time.start is None


def test_dated_weather_cause_establishes_the_reported_flood_occurrence():
    (mention,) = extract_mentions(
        "On 9 October 2026, heavy rainfall caused flooding in Lakeview. "
        "Two people died.",
        SOURCE,
    )
    assert mention.role == "reported"
    assert mention.time.start == datetime(2026, 10, 9, tzinfo=UTC)
    assert mention.place.wording == "Lakeview"
    assert mention.claims[0].fact.value == "Two"


@pytest.mark.parametrize(
    "text",
    [
        "On 9 October 2026, heavy rainfall could cause flooding in Lakeview.",
        "Officials reported on 9 October 2026 that rain caused flooding in Lakeview.",
        "The response on 9 October 2026 followed rain that caused flooding.",
    ],
)
def test_cause_language_does_not_override_forecast_or_reporting_clocks(text):
    mentions = extract_mentions(text, SOURCE)
    assert all(mention.time is None for mention in mentions)
