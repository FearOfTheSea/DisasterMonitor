"""Specific disaster-death snippets precede broad index themes, not headlines."""

from dataclasses import replace

import pytest

from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.news import NewsFeedItem

LEAD = NewsFeedItem(
    "lead", "Daily", "Recovery update", "https://daily.example/article", None, None
)


@pytest.mark.parametrize(
    "hint",
    [
        "Two workers died in the landslide.",
        "The earthquake killed residents in 2015.",
        "The flood left no survivors.",
        "Three firefighters lost their lives battling the wildfire.",
        "Les inondations ont fait deux morts.",
        "El deslizamiento de tierra dejó dos muertos.",
        "Banjir menyebabkan dua orang meninggal dunia.",
        "Duas pessoas morreram após o deslizamento.",
        "Heyelan sonucu bir kişi hayatını kaybetti.",
    ],
)
def test_specific_hazard_fatality_snippets_precede_generic_tags(hint):
    explicit = replace(LEAD, title="Two died in a flood")
    specific = replace(LEAD, discovery_hint=hint)
    weak = replace(LEAD, discovery_hint="flood; death-related index theme (unverified)")
    assert lead_retrieval_priority(explicit) == 3
    assert lead_retrieval_priority(specific) == 2
    assert lead_retrieval_priority(weak) == 1
    assert lead_retrieval_priority(LEAD) == 0


@pytest.mark.parametrize(
    "hint",
    [
        "No se han reportado personas heridas, fallecidas o desaparecidas.",
        "Tras el terremoto no se han reportado fallecidos.",
        "The flood killed two cattle.",
        "The earthquake could kill two people.",
        "The wildfire might leave no survivors.",
        "The flood is expected to claim many lives.",
        "A flood warning was issued. A driver died in a shooting.",
        "A driver died after an ATV crash.",
        "Der Fahrer starb bei einer Schießerei.",
        "A flood left no deaths or fatalities.",
        "There are fears that two workers drowned in the flood.",
    ],
)
def test_negative_nonhuman_future_and_separate_snippets_do_not_get_specific_priority(
    hint,
):
    lead = replace(LEAD, title="Landslide response", discovery_hint=hint)
    assert lead_retrieval_priority(lead) < 2


def test_snippet_selection_never_uses_the_url_or_publisher_as_a_signal():
    lead = replace(LEAD, discovery_hint="Two died in the flood.")
    other = replace(
        lead, canonical_url="https://other.example/no-deaths", publisher="Other"
    )
    assert lead_retrieval_priority(lead) == lead_retrieval_priority(other) == 2
