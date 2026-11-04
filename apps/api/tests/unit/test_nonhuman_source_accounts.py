"""Animal and plant losses do not establish human casualties."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Report", "https://daily.example/report", NOW, None, NOW
)


def fatalities(text):
    return [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "A wildfire killed 50 alpacas.",
        "A flood kills 200 cattle.",
        "Floods kill 200 cattle.",
        "A wildfire killed 50 llamas.",
        "There were 9,000 livestock fatalities within the burned area.",
        "There were almost 9,000 livestock fatalities within the LGA "
        "and 400,000 hectares of land burnt.",
        "A drought left dead trees across the region.",
        "Fifty cattle were killed in the wildfire.",
        "Un incendio forestal causó la muerte de más de 50 alpacas.",
        "Un incendio forestal provocó la muerte de más de 50 alpacas.",
        "Aproximadamente 4.000 animales han muerto por la sequía "
        "y el fenómeno de El Niño.",
        "Los animales murieron por el fenómeno climático El Niño.",
        "Livestock died during the El Niño weather pattern.",
        "Un incendie de forêt a tué trois moutons.",
        "Um incêndio matou 50 alpacas.",
        "Banjir menewaskan 50 sapi.",
    ],
)
def test_explicit_animal_or_plant_accounts_are_not_human_fatalities(text):
    assert not fatalities(text)


@pytest.mark.parametrize(
    "text",
    [
        "A wildfire killed John and 50 alpacas.",
        "A flood kills John and 50 alpacas.",
        "A wildfire killed 50 alpacas and John.",
        "John and 50 alpacas died in the wildfire.",
        "Marta y 50 alpacas murieron en el incendio forestal.",
        "50 alpacas y Marta murieron en el incendio forestal.",
        "Two people and 50 alpacas died in the wildfire.",
        "Dos personas y 50 alpacas murieron en el incendio forestal.",
    ],
)
def test_shared_human_and_animal_accounts_remain_visible_without_an_animal_toll(text):
    claims = fatalities(text)
    assert claims
    assert all(c.fact.value not in {"50", "52"} for c in claims)
    assert all(c.excerpt == text for c in claims)


@pytest.mark.parametrize(
    "text", ["A flood kills two people.", "Floods kill two people."]
)
def test_present_tense_human_fatalities_keep_the_attributed_count(text):
    (claim,) = fatalities(text)
    assert claim.fact.value == "two"
    assert claim.excerpt == text


def test_nonhuman_nominal_losses_do_not_hide_a_separate_human_death():
    text = (
        "Bushfires tore through the valley, killing one person. "
        "There were 9,000 livestock fatalities within the area."
    )
    (claim,) = fatalities(text)
    assert claim.fact.value == "one"
    assert claim.excerpt == "Bushfires tore through the valley, killing one person."


@pytest.mark.parametrize(
    "text",
    [
        "El niño murió en la inundación.",
        "El fenómeno de El Niño causó una sequía que mató a dos personas.",
        "Two people died while trying to rescue cattle from the flood.",
    ],
)
def test_literal_children_and_people_are_not_excluded_as_a_weather_name_or_animal_loss(
    text,
):
    assert fatalities(text)
