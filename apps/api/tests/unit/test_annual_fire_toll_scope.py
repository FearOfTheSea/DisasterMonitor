"""Annual multi-fire tolls cannot become a local fire's casualty count."""

import pytest

from disaster_monitor.domain.regional_accounts import regional_fatality_account


@pytest.mark.parametrize(
    "text",
    [
        "Víctimas mortales en 2026: los seis fallecidos por incendios forestales "
        "en la región se registraron en distintos distritos.",
        "Con él, suman seis las víctimas mortales en la región este año.",
    ],
)
def test_an_explicit_annual_fire_or_accumulating_toll_is_unallocated(text):
    claim = regional_fatality_account(text)
    assert claim is not None
    assert claim.value == "Unknown"
    assert {"scope unresolved", "combined occurrences"} <= set(claim.qualifiers)


def test_an_explicit_single_fire_count_is_not_hidden_by_its_year():
    claim = regional_fatality_account(
        "En 2026 seis personas murieron en un incendio forestal."
    )
    assert claim is not None
    assert claim.value == "6"
    assert "scope unresolved" not in claim.qualifiers
