"""Elided casualty lists must not give one hazard another episode's first toll."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Climate report", "https://daily.example/report", NOW, None, NOW
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
        "El informe cita las 14.000 muertes atribuidas a la ola de calor, "
        "las 708 causadas por las lluvias monzónicas y las 95 por el huracán Ada.",
        "Se registraron 20 muertes por calor, las 7 por inundaciones "
        "y las 3 por un huracán.",
        "Le rapport cite 20 morts dus à la chaleur, les 7 causés "
        "par les inondations et les 3 par un cyclone.",
        "O relatório cita 20 mortes pelo calor, as 7 causadas "
        "pelas enchentes e as 3 pelo ciclone.",
    ],
)
def test_causal_ellipsis_keeps_different_counts_unallocated(text):
    (claim,) = fatalities(text)
    assert claim.fact.value == "Unknown"
    assert {"uncertain", "scope unresolved"} <= set(claim.qualifiers)
    assert claim.excerpt == text


def test_a_hurricane_mention_does_not_take_the_heat_toll_from_a_global_report():
    text = (
        "El informe cita las 14.000 muertes atribuidas a la ola de calor, "
        "las 708 causadas por las lluvias monzónicas y las 95 por el huracán Ada."
    )
    result = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(1, NOW)
    )
    storms = [m for m in result.mentions if m.disaster is Disaster.TROPICAL_CYCLONE]
    assert storms
    for mention in storms:
        for claim in mention.claims:
            if claim.fact.category == "fatalities":
                assert claim.fact.value == "Unknown"
                assert claim.excerpt == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Se registraron 20 muertes por el huracán, las 20 por el mismo episodio.",
            "20",
        ),
        ("El huracán causó 20 muertes y los 700 refugios siguen abiertos.", "20"),
        ("El huracán causó 20 muertes y las 700 casas fueron destruidas.", "20"),
        (
            "Se registraron 20 muertes y las 30 por ciento de las viviendas "
            "dañadas requieren reparación.",
            "20",
        ),
        ("Le cyclone a causé 20 morts et les 700 maisons restent vides.", "20"),
        ("O ciclone causou 20 mortes e as 700 casas continuam vazias.", "20"),
    ],
)
def test_repeated_tolls_damage_and_percentages_do_not_supply_a_second_toll(
    text, expected
):
    (claim,) = fatalities(text)
    assert claim.fact.value == expected
