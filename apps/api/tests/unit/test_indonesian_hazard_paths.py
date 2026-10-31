"""Native hazard wording follows the same source-account and uncertainty rules."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text

NOW = datetime(2026, 10, 26, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Regional News",
    "Regional bulletin",
    "https://regional.example/story",
    NOW,
    None,
    NOW,
)
CASES = (
    ("kebakaran hutan", Disaster.WILDFIRE),
    ("kebakaran lahan", Disaster.WILDFIRE),
    ("karhutla", Disaster.WILDFIRE),
    ("kekeringan", Disaster.DROUGHT),
    ("siklon tropis", Disaster.TROPICAL_CYCLONE),
    ("badai tropis", Disaster.TROPICAL_CYCLONE),
    ("topan", Disaster.TROPICAL_CYCLONE),
    ("erupsi gunung api", Disaster.VOLCANIC_ERUPTION),
    ("letusan gunungapi", Disaster.VOLCANIC_ERUPTION),
    ("Gunung Contoh meletus", Disaster.VOLCANIC_ERUPTION),
)


def report(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )


def positive_claims(result):
    return [
        c
        for m in result.mentions
        if m.role in ("reported", "ongoing", "historical")
        for c in m.claims
        if c.fact.category == "fatalities" and c.fact.value not in ("Unknown", "0")
    ]


@pytest.mark.parametrize(("hazard_wording", "hazard"), CASES)
def test_native_hazard_and_human_deaths_remain_attributed(hazard_wording, hazard):
    text = f"Dua orang meninggal akibat {hazard_wording}."
    assert disasters_in_text(text) == (hazard,)
    result = report(text)
    assert result.article.text == text
    assert any(
        c.fact.value == "2" and c.excerpt == text and c.fact.source == SOURCE
        for c in positive_claims(result)
    )
    assert all(m.time is None for m in result.mentions)


@pytest.mark.parametrize(("hazard_wording", "hazard"), CASES)
def test_hazard_forecast_zero_unknown_and_nonhuman_loss_are_distinct(
    hazard_wording, hazard
):
    forecast = report(
        f"Simulasi {hazard_wording} digelar; bencana diprediksi menewaskan dua orang."
    )
    assert forecast.mentions and all(m.role == "forecast" for m in forecast.mentions)
    assert not positive_claims(forecast)
    for text in (
        f"Tidak ada orang meninggal akibat {hazard_wording}.",
        f"Belum ada laporan korban jiwa akibat {hazard_wording}.",
        f"{hazard_wording} menewaskan tiga sapi.",
    ):
        result = report(text)
        assert result.mentions
        assert not positive_claims(result)


@pytest.mark.parametrize(
    "text",
    [
        "Kebakaran rumah menewaskan dua orang.",
        "Kekeringan kulit menyebabkan nyeri.",
        "Erupsi gigi menyebabkan nyeri.",
        "Badai ekonomi memengaruhi pasar.",
        "Puting beliung merusak rumah.",
    ],
)
def test_other_fire_medical_and_storm_meanings_do_not_become_these_disasters(text):
    assert not disasters_in_text(text)


@pytest.mark.parametrize("verb", ["ditembak", "tertembak", "dibunuh"])
def test_an_armed_killing_during_firefighting_is_not_a_wildfire_death(verb):
    result = report(f"Dua petugas tewas {verb} saat menangani kebakaran hutan.")
    assert result.mentions
    assert not positive_claims(result)


@pytest.mark.parametrize("verb", ["menyebabkan", "mengakibatkan"])
def test_literal_causation_keeps_following_local_fatality_reporting(verb):
    text = f"Cuaca ekstrem {verb} kekeringan. Akibatnya, dua orang meninggal dunia."
    result = report(text)
    assert any(c.fact.value == "2" for c in positive_claims(result))
    assert result.article.text == text
    future = report(
        f"Cuaca ekstrem diprediksi {verb} kekeringan. "
        "Akibatnya, dua orang diprediksi meninggal dunia."
    )
    assert not positive_claims(future)
