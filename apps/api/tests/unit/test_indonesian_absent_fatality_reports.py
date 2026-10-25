"""Absent reports are uncertainty; explicit absence is a reported zero."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Source", "https://daily.example/report", NOW, None, NOW
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
        "Tidak terdapat laporan korban meninggal akibat banjir.",
        "Tidak ada laporan korban meninggal dunia akibat tanah longsor.",
        "Belum ada laporan korban jiwa akibat gempa bumi.",
    ],
)
def test_no_fatality_reporting_is_neither_a_positive_toll_nor_a_verified_zero(text):
    (claim,) = fatalities(text)
    assert claim.fact.value == "Unknown"
    assert "uncertain" in claim.qualifiers
    assert claim.excerpt == text


@pytest.mark.parametrize(
    "text",
    [
        "Tidak ada korban meninggal akibat banjir.",
        "Tidak terdapat korban jiwa akibat gempa bumi.",
    ],
)
def test_explicit_no_fatalities_is_retained_as_zero(text):
    (claim,) = fatalities(text)
    assert claim.fact.value == "0"


@pytest.mark.parametrize(
    "text",
    [
        "Dua orang meninggal akibat banjir.",
        "Petugas terdapat di lokasi dan satu orang meninggal akibat tanah longsor.",
    ],
)
def test_actual_fatalities_remain_visible(text):
    (claim,) = fatalities(text)
    assert claim.fact.value in {"1", "2"}
