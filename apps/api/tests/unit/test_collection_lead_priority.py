"""Retrieval hints change inspection order, never source eligibility."""

from dataclasses import replace

import pytest

from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.news import NewsFeedItem

LEAD = NewsFeedItem(
    "lead", "Daily", "Flood warning", "https://daily.example/article", None, None
)


@pytest.mark.parametrize(
    ("title", "hint", "priority"),
    [
        ("El frente frío dejó diez muertos y graves inundaciones", None, 1),
        ("Las inundaciones dejaron cuatro personas muertas", None, 1),
        ("Les inondations ont fait deux morts", None, 1),
        ("No hubo muertos en las inundaciones", None, 0),
        ("Le bilan des morts reste inconnu", None, 0),
        ("Four firefighters die battling a wildfire", None, 1),
        ("A flood killed two people", None, 1),
        ("Responders cite staffing gaps in deadly 2025 flood", None, 1),
        ("Article title unavailable", "Deadly landslide response reviewed", 1),
        ("Flood was not deadly", None, 0),
        ("No deadly floods reported", None, 0),
        ("Deadliness of a future flood is uncertain", None, 0),
        ("Article title unavailable", "A landslide leaves five dead", 1),
        ("No deaths reported after the earthquake", None, 0),
        ("Floods leave four people missing", None, 0),
        ("Thousands evacuated before the storm", None, 0),
        ("Mulher morre após deslizamento de terra", None, 1),
        ("Deslizamento mata duas pessoas", None, 1),
        ("Deslizamento mata 12 trabalhadores", None, 1),
        ("Enchente atinge a mata atlântica", None, 0),
        ("A mata recebe duas pessoas para pesquisa", None, 0),
        ("Não morre ninguém após a enchente", None, 0),
    ],
)
def test_fatality_hints_get_priority_while_missing_only_and_zero_accounts_do_not(
    title, hint, priority
):
    lead = replace(LEAD, title=title, discovery_hint=hint)
    assert lead_retrieval_priority(lead) == priority
