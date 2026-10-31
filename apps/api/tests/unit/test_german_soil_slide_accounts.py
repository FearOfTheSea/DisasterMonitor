"""Literal German soil-slide reporting stays separate from snow and forecasts."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.mention_extraction import extract_mentions
from disaster_monitor.domain.regional_accounts import regional_fatality_account

SOURCE = SourceReference(
    "news",
    "Daily",
    "Regionalbericht",
    "https://daily.example/report",
    datetime(2026, 10, 24, tzinfo=UTC),
    None,
    datetime(2026, 10, 24, tzinfo=UTC),
)


@pytest.mark.parametrize(
    "hazard",
    [
        "Erdrutsch",
        "Erdrutsche",
        "Erdrutschen",
        "Schlammlawine",
        "Kohleschlammlawine",
        "Felssturz",
    ],
)
def test_explicit_german_soil_and_rock_movement_is_a_landslide(hazard):
    assert disasters_in_text(f"Zwei Menschen starben bei einem {hazard}.") == (
        Disaster.LANDSLIDE,
    )


@pytest.mark.parametrize(
    "text",
    [
        "Eine Lawine tötete zwei Menschen.",
        "Zwei Skifahrer starben bei einer Schneelawine.",
        "Ein Erdrutschgebiet wurde abgesperrt.",
        "Erdrutschgefahr besteht nach Regen.",
    ],
)
def test_snow_and_hazard_related_compounds_do_not_establish_a_soil_slide(text):
    assert Disaster.LANDSLIDE not in disasters_in_text(text)


@pytest.mark.parametrize(
    ("wording", "count"),
    [
        ("Zwei Menschen starben bei einem Erdrutsch.", "2"),
        ("Drei Kinder kamen bei der Schlammlawine ums Leben.", "3"),
        ("Vier Menschen kamen ums Leben, als eine Schlammlawine Häuser begrub.", "4"),
        ("Bei einem Erdrutsch wurden zwei Menschen getötet.", "2"),
        ("Zwei Menschen wurden bei einem Erdrutsch getötet.", "2"),
    ],
)
def test_literal_german_death_accounts_keep_their_attributed_count(wording, count):
    claim = regional_fatality_account(wording)
    assert claim is not None
    assert claim.value == count


def test_children_and_adults_are_not_a_partial_or_computed_total():
    text = (
        "116 Kinder und 28 Erwachsene kamen ums Leben, "
        "als eine Kohleschlammlawine die Schule begrub."
    )
    claims = [
        c
        for m in extract_mentions(text, SOURCE)
        for c in m.claims
        if c.fact.category == "fatalities"
    ]
    assert claims
    assert all(c.fact.value == "Unknown" for c in claims)
    assert all("scope unresolved" in c.qualifiers for c in claims)
    assert all(c.excerpt == text for c in claims)


@pytest.mark.parametrize(
    "text",
    [
        "Zwei Kinder und drei Erwachsene starben bei einem Erdrutsch.",
        "Dos niños y tres personas murieron en un deslizamiento de tierra.",
        "Deux enfants et trois personnes sont morts dans un glissement de terrain.",
    ],
)
def test_coordinated_regional_populations_remain_unallocated(text):
    claim = regional_fatality_account(text)
    assert claim is not None
    assert claim.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Keine Menschen starben bei einem Erdrutsch.", "0"),
        ("Niemand kam ums Leben, als eine Schlammlawine Häuser begrub.", "0"),
        ("Die Zahl der bei dem Erdrutsch Gestorbenen ist unbekannt.", "Unknown"),
        (
            "Bei einer Übung wurden zwei Menschen durch einen Erdrutsch getötet.",
            "Unknown",
        ),
        ("Zwei Menschen könnten bei einem Erdrutsch getötet werden.", "Unknown"),
    ],
)
def test_denials_unknown_counts_and_simulations_do_not_establish_positive_tolls(
    text, expected
):
    claim = regional_fatality_account(text)
    assert claim is not None
    assert claim.value == expected


def test_only_dead_animals_are_not_human_fatality_accounts():
    assert regional_fatality_account("Zwei Kühe starben bei einem Erdrutsch.") is None


@pytest.mark.parametrize(
    "text",
    [
        "Die Schlammlawine zerstörte Häuser.",
        "Die Menschen wurden nach dem Erdrutsch gerettet.",
    ],
)
def test_german_articles_are_not_the_english_verb_die(text):
    assert not [
        c
        for m in extract_mentions(text, SOURCE)
        for c in m.claims
        if c.fact.category == "fatalities"
    ]


def test_fighting_for_life_does_not_assert_a_death():
    assert (
        regional_fatality_account("Nach dem Erdrutsch kämpft ein Mann ums Leben.")
        is None
    )


@pytest.mark.parametrize("day", ["4.", "21."])
def test_an_ordinal_day_does_not_cut_the_fatality_from_its_soil_slide(day):
    text = (
        f"116 Kinder und 28 Erwachsene kamen ums Leben, als am {day} Oktober 1966 "
        "eine Kohleschlammlawine die Schule begrub."
    )
    claims = [
        c
        for m in extract_mentions(text, SOURCE)
        for c in m.claims
        if c.fact.category == "fatalities"
    ]
    assert claims
    assert all(c.fact.value == "Unknown" for c in claims)
    assert all("scope unresolved" in c.qualifiers for c in claims)
    assert all(c.excerpt == text for c in claims)
    assert all(
        m.time is None or m.time.start is None for m in extract_mentions(text, SOURCE)
    )


def test_an_ordinary_sentence_ending_with_a_count_is_still_separate():
    from disaster_monitor.domain.source_sentences import source_sentences

    text = "The earthquake death toll reached 12. Officials reported two injuries."
    assert source_sentences(text) == [
        "The earthquake death toll reached 12.",
        "Officials reported two injuries.",
    ]


def test_later_german_articles_do_not_become_additional_death_claims():
    text = (
        "Zwei Menschen starben bei einer Schlammlawine. "
        "Die Queen bereute ihre Reaktion auf die Katastrophe ihr Leben lang."
    )
    claims = [
        c
        for m in extract_mentions(text, SOURCE)
        for c in m.claims
        if c.fact.category == "fatalities"
    ]
    assert claims
    assert all(c.fact.value == "2" for c in claims)
    assert all("Die Queen" not in c.excerpt for c in claims)


@pytest.mark.parametrize(
    "text", ["People die in floods.", "TWO PEOPLE DIE IN A FLOOD."]
)
def test_english_die_predicates_are_still_available(text):
    from disaster_monitor.domain.reported_impacts import extract_reported_impacts

    claims = [
        c
        for c in extract_reported_impacts(text, SOURCE)
        if c.fact.category == "fatalities"
    ]
    assert claims


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Im Jahr 1966 starben zwei Menschen bei einem Erdrutsch.", "2"),
        ("Am 21. Oktober 1966 starben zwei Kinder bei einer Schlammlawine.", "2"),
        ("Bei einem Erdrutsch starben zwei Menschen.", "2"),
        ("Bei einem Erdrutsch starben zwei Kinder und drei Erwachsene.", "Unknown"),
        (
            "Die 47 Jahre alte Frau ist bei einem Erdrutsch gestorben.",
            "Reported; count unknown",
        ),
        ("47 Menschen starben bei einem Erdrutsch.", "47"),
    ],
)
def test_calendars_ages_and_german_subject_order_preserve_count_scope(text, expected):
    claim = regional_fatality_account(text)
    assert claim is not None
    assert claim.value == expected


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        ("116 Kinder starben: Gedenken nach der Katastrophe", 3),
        ("Keine Menschen starben bei einem Erdrutsch", 0),
    ],
)
def test_headline_priority_uses_the_same_fatality_wording(headline, expected):
    from disaster_monitor.domain.collection import lead_retrieval_priority
    from disaster_monitor.domain.news import NewsFeedItem

    lead = NewsFeedItem(
        "n", "Daily", headline, "https://daily.example/report", None, None
    )
    assert lead_retrieval_priority(lead) == expected
