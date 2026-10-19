"""Source accounts remain inspectable without selecting a winning claim."""

from datetime import UTC, datetime

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

SOURCE = SourceReference(
    "news",
    "Daily",
    "Flood update",
    "https://daily.example/flood",
    datetime(2026, 10, 17, tzinfo=UTC),
    None,
    datetime(2026, 10, 18, tzinfo=UTC),
)


def test_alternative_outcomes_are_retained_without_asserting_deaths_or_injuries():
    (deaths, injuries) = extract_reported_impacts(
        "The clinician said patients either did not have injuries "
        "or were dead or missing.",
        SOURCE,
    )
    assert deaths.fact.value == injuries.fact.value == "Unknown"
    assert "uncertain" in deaths.qualifiers and "uncertain" in injuries.qualifiers
    assert "dead or missing" in deaths.excerpt


def test_retains_corrected_historical_uncertain_zero_and_scoped_accounts():
    text = (
        "Preliminary reports said 12 people died in North Province on Monday. "
        "A correction says 10 people died across the country on Tuesday. "
        "No injuries were reported in Riverton. "
        "The number of displaced people remains unknown. "
        "Five people may have died last year."
    )
    claims = extract_reported_impacts(text, SOURCE, location="Riverton")
    assert [c.fact.category for c in claims] == [
        "fatalities",
        "fatalities",
        "injuries",
        "displacement",
        "fatalities",
    ]
    assert [c.fact.value for c in claims] == ["12", "10", "0", "Unknown", "Five"]
    assert "preliminary" in claims[0].qualifiers
    assert "corrected" in claims[1].qualifiers
    assert set(claims[-1].qualifiers) == {"historical", "uncertain"}
    assert claims[0].excerpt.endswith("North Province on Monday.")
    assert all(c.fact.source == SOURCE for c in claims)


def test_only_in_scope_infrastructure_and_no_invented_counts():
    claims = extract_reported_impacts(
        "Roads and bridges were washed away. Electricity networks were damaged. "
        "Water systems were disrupted. Communications networks are down. "
        "Schools and hospitals were destroyed. Property losses reached $5 million. "
        "Officials met 12 people; deaths remain unknown.",
        SOURCE,
    )
    assert [c.fact.category for c in claims] == [
        "roads_bridges",
        "electricity",
        "water",
        "communications",
        "fatalities",
    ]
    assert claims[-1].fact.value == "Unknown"
    assert all(len(c.excerpt) <= 600 for c in claims)


def test_each_count_is_tied_to_its_impact_not_an_unrelated_number():
    claims = extract_reported_impacts(
        "On October 12, 4 people died and 20 were injured. "
        "There were 200 people displaced, including 50 in Riverton. "
        "The flood killed two people.",
        SOURCE,
    )
    assert [(c.fact.category, c.fact.value) for c in claims] == [
        ("fatalities", "4"),
        ("injuries", "20"),
        ("displacement", "200"),
        ("fatalities", "two"),
    ]


def test_no_one_died_is_zero_not_one():
    claims = extract_reported_impacts("No one died. No people were injured.", SOURCE)
    assert [c.fact.value for c in claims] == ["0", "0"]


def test_qualitative_blocked_roads_and_drinking_water_damage_remain_attributed():
    road = "Rain and storm surge flooded coastal areas and blocked roads in Guerrero."
    water = (
        "The earthquake damaged essential drinking water and transportation "
        "infrastructure in the affected provinces."
    )
    claims = extract_reported_impacts(
        f"{road} {water}", SOURCE, location="Source region"
    )
    assert [(c.fact.category, c.fact.value) for c in claims] == [
        ("roads_bridges", "Source account"),
        ("water", "Source account"),
    ]
    assert [c.excerpt for c in claims] == [road, water]
    assert all(c.fact.source == SOURCE for c in claims)
    assert all(c.fact.reported_location == "Source region" for c in claims)


def test_infrastructure_mentions_without_a_supported_impact_are_not_damage():
    assert not extract_reported_impacts(
        "Teams distributed drinking water and cleared rubbish near roads. "
        "The water infrastructure inspection is planned. "
        "Schools were damaged near a water distribution point.",
        SOURCE,
    )


def test_provider_accounts_only_attach_matching_supporting_excerpts():
    from disaster_monitor.domain.evidence import ReportedFact, SituationReport
    from disaster_monitor.domain.evidence_types import FactStatus
    from disaster_monitor.domain.reported_impacts import inspect_report_impacts

    report = SituationReport(
        SOURCE,
        "Roads were damaged. Preliminary reports said 10 people died. "
        "A correction says 12 people died. Two people were injured.",
        facts=tuple(
            ReportedFact(category, label, value, FactStatus.UNKNOWN, SOURCE)
            for category, label, value in (
                ("fatalities", "Deaths", "12"),
                ("injuries", "Injured", "2"),
                ("displacement", "Displaced", "300"),
            )
        ),
    )
    accounts = inspect_report_impacts(report)
    assert accounts[0].excerpt == "A correction says 12 people died."
    assert "corrected" in accounts[0].qualifiers
    assert accounts[1].excerpt == "Two people were injured."
    assert accounts[2].excerpt == ""
    assert accounts[2].fact.value == "300"
