"""Explicit absence wording must not turn into an unspecified casualty account."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 23, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Report", "https://daily.example/report", NOW, None, NOW
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The volcano erupted without injuries or deaths.", "0"),
        ("The road reopened without any reported fatalities.", "0"),
        ("The wildfire ended without one person being killed.", "0"),
        ("The flood killed three people without warning.", "three"),
        ("Three people died without receiving assistance.", "Three"),
    ],
)
def test_absence_of_impacts_is_distinct_from_absence_of_warning_or_assistance(
    text, expected
):
    (claim,) = [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]
    assert claim.fact.value == expected
    assert claim.excerpt == text
