"""Physical movement is not a human displacement account."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 8, 15, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Local Daily",
    "Earthquake account",
    "https://daily.example/quake",
    NOW,
    None,
    NOW,
)


def displacement(text):
    return [
        claim
        for claim in extract_reported_impacts(text, SOURCE)
        if claim.fact.category == "displacement"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "The earthquake displaced the seafloor enough to cause a tsunami.",
        "The rupture produced a large displacement on the fault near the coast.",
        "The tectonic plates were displaced by two metres.",
        "The horizontal displacement of the seabed reached five metres.",
        "Ground displacement was measured after the earthquake.",
        "The earthquake caused displacement of the crust.",
        "Three metres of fault displacement were measured.",
        "Water was displaced by the landslide.",
        "Sensors measured the displacement of sediment.",
        "Displaced rocks blocked the road after the earthquake.",
    ],
)
def test_explicit_physical_displacement_is_not_a_human_impact(text):
    assert not displacement(text)


@pytest.mark.parametrize(
    "text,value",
    [
        ("The quake displaced the seafloor, while 300 people were displaced.", "300"),
        (
            "Seafloor displacement reached five metres, "
            "while 300 residents were displaced.",
            "300",
        ),
        ("The landslide displaced soil and left 20 people homeless.", "20"),
        (
            "Three people were displaced after a landslide moved displaced rocks.",
            "Three",
        ),
        ("No residents were displaced despite fault displacement.", "0"),
        (
            "The number of displaced people remains unknown "
            "despite ground displacement.",
            "Unknown",
        ),
        ("Human displacement along the fault remains unknown.", "Unknown"),
        (
            "Residents were displaced along a fault after the earthquake.",
            "Reported; count unknown",
        ),
        ("Displacement of 120 people was reported after the flood.", "120"),
        ("People were displaced by the earthquake.", "Reported; count unknown"),
    ],
)
def test_real_human_accounts_survive_physical_movement_in_the_same_sentence(
    text, value
):
    (claim,) = displacement(text)
    assert claim.fact.value == value
    assert claim.excerpt == text and claim.fact.source == SOURCE


def test_other_impacts_are_not_removed_with_geological_movement():
    text = "Displaced sediment blocked roads and injured two people."
    claims = extract_reported_impacts(text, SOURCE)
    assert {claim.fact.category: claim.fact.value for claim in claims} == {
        "injuries": "two",
        "roads_bridges": "Source account",
    }
    assert all(claim.excerpt == text for claim in claims)


@pytest.mark.parametrize(
    "text,value",
    [
        ("Ground displacement of two metres left 500 residents displaced.", "500"),
        (
            "The earthquake displaced the seafloor and 300 people.",
            "Reported; count unknown",
        ),
        (
            "Displacement of sediment and residents was reported.",
            "Reported; count unknown",
        ),
        (
            "The earthquake displaced water workers from their homes.",
            "Reported; count unknown",
        ),
        ("The earthquake displaced rock-climbers.", "Reported; count unknown"),
        ("The quake displaced 30 people and moved the seafloor.", "30"),
        ("The rocks displaced 20 residents from their homes.", "20"),
    ],
)
def test_coordinated_and_modified_human_populations_are_not_erased(text, value):
    (claim,) = displacement(text)
    assert claim.fact.value == value and claim.excerpt == text


@pytest.mark.parametrize(
    "text",
    [
        "The rocks were displaced and 20 people were injured.",
        "Ground displacement and 20 people injured were reported after the quake.",
        "The quake displaced the seafloor and 20 people were injured.",
    ],
)
def test_another_human_impact_does_not_make_physical_movement_human_displacement(text):
    claims = extract_reported_impacts(text, SOURCE)
    assert not [claim for claim in claims if claim.fact.category == "displacement"]
    assert any(claim.fact.category == "injuries" for claim in claims)
