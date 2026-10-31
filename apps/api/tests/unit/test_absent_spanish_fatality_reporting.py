"""Absence of a report is not an attributed fatality or a verified zero."""

import pytest

from disaster_monitor.domain.regional_accounts import regional_fatality_account


@pytest.mark.parametrize(
    "text",
    [
        (
            "Tras el sismo, no se han reportado personas heridas, "
            "fallecidas o desaparecidas."
        ),
        "El derrumbe no se ha reportado con muertos.",
        "Por las inundaciones no se reportan fallecidos.",
        "No se reportaron muertes tras el terremoto.",
    ],
)
def test_absent_spanish_reporting_is_unknown(text):
    account = regional_fatality_account(text)
    assert account is not None
    assert account.value == "Unknown"
    assert "uncertain" in account.qualifiers


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "No se reportan heridos, pero dos personas murieron en el deslizamiento.",
            "2",
        ),
        ("No se han reportado heridos; hay dos fallecidos por las inundaciones.", "2"),
        ("No se reportan fallecidos en A, pero dos murieron en B.", "Unknown"),
        ("No hubo muertos tras el terremoto.", "0"),
    ],
)
def test_absence_cannot_cross_a_positive_clause_or_replace_explicit_zero(
    text, expected
):
    account = regional_fatality_account(text)
    assert account is not None
    assert account.value == expected


def test_mixed_absent_and_positive_reporting_keeps_scope_unresolved():
    account = regional_fatality_account(
        "No se reportan fallecidos en A, pero dos murieron en B."
    )
    assert account is not None
    assert account.value == "Unknown"
    assert "scope unresolved" in account.qualifiers
