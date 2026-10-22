"""Literal Indonesian quake/fatality wording preserves original source evidence."""

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
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 22, tzinfo=UTC)
SOURCE = SourceReference(
    "news",
    "Regional News",
    "Regional bulletin",
    "https://regional.example/story",
    NOW,
    None,
    NOW,
)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Satu orang dilaporkan meninggal dunia setelah gempa bumi.", "1"),
        ("Gempa tersebut menewaskan dua orang.", "2"),
        ("Gempa mengguncang wilayah itu, tiga warga tewas.", "3"),
        ("Gempa bumi terjadi; 12 orang meninggal.", "12"),
        (
            "Seorang warga berusia 73 tahun meninggal setelah gempa.",
            "Reported; count unknown",
        ),
    ],
)
def test_indonesian_quake_accounts_are_attributed_without_inventing_onset_or_location(
    text, value
):
    assert disasters_in_text(text) == (Disaster.EARTHQUAKE,)
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert any(c.fact.value == value and c.excerpt in text for c in claims)
    assert report.article.text == text
    assert all(m.time is None for m in report.mentions)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Tidak ada korban jiwa akibat gempa bumi.", "0"),
        ("Tidak ada orang meninggal akibat gempa.", "0"),
        ("Belum diketahui jumlah korban jiwa setelah gempa.", "Unknown"),
        ("Gempa diprediksi menewaskan 10 orang.", "Unknown"),
        ("Gempa menyebabkan lima orang tewas atau hilang.", "Unknown"),
    ],
)
def test_absence_unknown_forecast_and_combined_status_do_not_create_positive_tolls(
    text, value
):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == value


def test_indonesian_forecast_is_not_a_reported_physical_occurrence():
    report = assess_article(
        DiscoveryArticle(
            SOURCE, "Simulasi gempa bumi digelar; gempa diprediksi menewaskan 10 orang."
        ),
        ReportingInterval.at_start(3, NOW),
    )
    assert report.mentions
    assert all(m.role == "forecast" for m in report.mentions)


def test_animal_only_losses_are_not_human_fatalities():
    assert not extract_reported_impacts("Gempa menewaskan tiga sapi.", SOURCE)


def test_competing_armed_cause_is_not_assigned_to_a_quake():
    report = assess_article(
        DiscoveryArticle(
            SOURCE, "Gempa terjadi, serangan bersenjata menewaskan tiga orang."
        ),
        ReportingInterval.at_start(3, NOW),
    )
    assert report.mentions
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


def test_indonesian_minimum_is_preserved_as_an_uncertain_account():
    (claim,) = extract_reported_impacts(
        "Gempa menewaskan sedikitnya dua orang.", SOURCE
    )
    assert claim.fact.value == "2"
    assert "uncertain" in claim.qualifiers
