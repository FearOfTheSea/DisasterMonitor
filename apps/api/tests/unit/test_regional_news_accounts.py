"""Literal Spanish/French source accounts retain uncertainty and attribution."""

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
    "Regional Daily",
    "Regional bulletin",
    "https://daily.example/bulletin",
    NOW,
    None,
    NOW,
)


@pytest.mark.parametrize(
    ("spanish", "french", "hazard"),
    [
        ("Un terremoto", "Un séisme", Disaster.EARTHQUAKE),
        ("Las inundaciones", "Les inondations", Disaster.FLOOD),
        ("Un incendio forestal", "Un incendie de forêt", Disaster.WILDFIRE),
        ("Un deslizamiento de tierra", "Un glissement de terrain", Disaster.LANDSLIDE),
        ("La sequía", "La sécheresse", Disaster.DROUGHT),
        ("El huracán", "La tempête tropicale", Disaster.TROPICAL_CYCLONE),
        ("La erupción volcánica", "L’éruption volcanique", Disaster.VOLCANIC_ERUPTION),
    ],
)
def test_regional_hazard_words_share_the_same_supported_categories(
    spanish, french, hazard
):
    assert disasters_in_text(spanish) == disasters_in_text(french) == (hazard,)


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Las inundaciones dejaron cuatro personas muertas.", "4"),
        ("Dos trabajadores murieron tras el deslizamiento de tierra.", "2"),
        ("Las inundaciones causaron la muerte de 12 personas.", "12"),
        (
            "Un hombre de 74 años murió tras las inundaciones.",
            "Reported; count unknown",
        ),
        ("Les inondations ont fait quatre morts.", "4"),
        ("Le glissement de terrain a tué deux personnes.", "2"),
        ("Deux personnes sont mortes dans les inondations.", "2"),
        (
            "Un homme de 74 ans est mort dans les inondations.",
            "Reported; count unknown",
        ),
        (
            "Ces inondations ont provoqué des pertes en vies humaines.",
            "Reported; count unknown",
        ),
    ],
)
def test_fatality_accounts_keep_the_original_sentence_and_publisher(sentence, expected):
    claims = [
        c
        for c in extract_reported_impacts(sentence, SOURCE)
        if c.fact.category == "fatalities"
    ]
    assert len(claims) == 1
    assert claims[0].fact.value == expected
    assert claims[0].excerpt == sentence
    assert claims[0].fact.source == SOURCE


@pytest.mark.parametrize(
    "text",
    [
        "Se prevén inundaciones que podrían causar cuatro muertes.",
        "Une simulation de séisme pourrait faire quatre morts.",
    ],
)
def test_forecasts_and_simulations_do_not_acquire_fatality_claims(text):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions
    assert all(m.role == "forecast" for m in report.mentions)
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("No hubo muertos en las inundaciones.", "0"),
        ("Aucun mort dans les inondations.", "0"),
        ("No hay reportes de muertes por las inundaciones.", "Unknown"),
        ("Le bilan des morts des inondations reste inconnu.", "Unknown"),
        ("Cuatro muertos o desaparecidos tras las inundaciones.", "Unknown"),
        ("Quatre morts ou disparus après les inondations.", "Unknown"),
    ],
)
def test_zero_unknown_and_combined_outcomes_do_not_assert_positive_deaths(
    sentence, expected
):
    claims = [
        c
        for c in extract_reported_impacts(sentence, SOURCE)
        if c.fact.category == "fatalities"
    ]
    assert len(claims) == 1
    assert claims[0].fact.value == expected


@pytest.mark.parametrize(
    "text",
    [
        "Las inundaciones mataron doce vacas.",
        "Les inondations ont tué douze vaches.",
        "Le séisme a frappé la région, mais une fusillade a fait quatre morts.",
        "Las inundaciones afectaron la región y un ataque armado dejó dos muertos.",
    ],
)
def test_animal_deaths_and_competing_armed_causes_do_not_become_disaster_fatalities(
    text,
):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )
    assert report.article.text == text


@pytest.mark.parametrize(
    "text",
    [
        "No se reportan fallecidos ni desaparecidos tras el terremoto.",
        "No se reportan personas fallecidas por el sismo.",
    ],
)
def test_retained_spanish_present_tense_denials_are_not_positive_fatalities(text):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "0"


@pytest.mark.parametrize(
    "text",
    [
        "Floods cause death and destruction every year.",
        "Flood warnings issued Tue.",
    ],
)
def test_regional_vocabulary_does_not_turn_english_context_into_casualty_reporting(
    text,
):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


@pytest.mark.parametrize(
    "text",
    [
        "El frente frío dejó diez personas muertas y severas inundaciones.",
        "La tempête a causé dix morts et des inondations.",
        "Se confirmaron cuatro fallecimientos en Villa Clara, "
        "pero no se incluyeron las seis muertes de otro municipio.",
    ],
)
def test_broader_weather_and_multiple_local_totals_are_not_allocated_to_one_flood(text):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers
    assert claim.excerpt == text


def test_explicit_flood_fatality_link_is_retained_despite_a_broader_weather_context():
    (claim,) = extract_reported_impacts(
        "Las inundaciones causadas por el frente frío mataron cuatro personas.", SOURCE
    )
    assert claim.fact.value == "4"


def test_mixed_carbon_monoxide_and_flood_episode_does_not_create_a_flood_total():
    text = (
        "Las inundaciones dejaron once muertos: cuatro tras el derrumbe "
        "de una barda, seis por intoxicación con monóxido de carbono "
        "y un conductor arrastrado por el agua."
    )
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )
    assert report.article.text == text


@pytest.mark.parametrize(
    "text",
    [
        "La sequía afectó las flores para el Día de Muertos.",
        "Prevén desabasto de flores para Día de los Muertos por la sequía.",
    ],
)
def test_named_holiday_is_not_a_report_of_human_deaths(text):
    from disaster_monitor.domain.regional_accounts import regional_occurrence_start

    assert not extract_reported_impacts(text, SOURCE)
    assert regional_occurrence_start(text) is None


def test_actual_fatality_account_survives_a_holiday_mention():
    text = "Las inundaciones dejaron dos muertos durante el Día de Muertos."
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "2"
    assert claim.excerpt == text


def test_ceremonial_altars_do_not_make_crop_losses_into_human_deaths():
    text = "La sequía redujo las flores que adornan altares de muertos."
    assert not extract_reported_impacts(text, SOURCE)


def test_human_toll_remains_when_the_same_sentence_mentions_ceremonial_altars():
    text = (
        "Las inundaciones dejaron dos muertos; "
        "sus familias colocaron altares de muertos."
    )
    claims = extract_reported_impacts(text, SOURCE)
    assert any(c.fact.value == "2" for c in claims)
