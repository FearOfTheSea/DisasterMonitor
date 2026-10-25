"""Turkish mass-movement accounts retain literal fatality and episode scope."""

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

NOW = datetime(2026, 10, 25, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Yerel haber", "https://daily.example/report", NOW, None, NOW
)


def assess(text):
    return assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )


def tolls(report):
    return [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]


@pytest.mark.parametrize(
    "term",
    [
        "heyelan",
        "heyelanda",
        "heyelanı",
        "heyelanın",
        "heyelanında",
        "heyelanlar",
        "heyelanlarda",
        "heyelanlarının",
        "HEYELANDA",
        "toprak kayması",
        "toprak kaymasında",
        "toprak kaymasının",
        "toprak kaymaları",
        "toprak kaymalarında",
        "kaya düşmesi",
        "kaya düşmesinde",
        "kaya düşmesinin",
        "kaya düşmeleri",
        "kaya düşmelerinde",
    ],
)
def test_literal_singular_and_plural_mass_movement_wording(term):
    assert disasters_in_text(term) == (Disaster.LANDSLIDE,)


@pytest.mark.parametrize(
    "text,value",
    [
        ("Heyelan sonucu bir kişi hayatını kaybetti.", "1"),
        ("Heyelanda üç kişi hayatını kaybetti.", "3"),
        ("Toprak kaymasında iki işçi öldü.", "2"),
        ("Kaya düşmesinde bir kişi yaşamını yitirdi.", "1"),
        ("Heyelanda hayatını kaybeden üç kişi anıldı.", "3"),
        ("HEYELANDA ALTI KİŞİ HAYATINI KAYBETTİ.", "6"),
        ("Heyelanda 45 yaşındaki kişi öldü.", "Reported; count unknown"),
        ("Heyelanda can kaybı olduğu bildirildi.", "Reported; count unknown"),
    ],
)
def test_reported_human_deaths_are_accessible_with_unresolved_onset_and_place(
    text, value
):
    report = assess(text)
    assert report.eligibility == "eligible"
    assert report.article.text == text
    claims = tolls(report)
    assert len(claims) == 1
    assert claims[0].fact.value == value
    assert claims[0].excerpt == text and claims[0].fact.source == SOURCE
    assert all(m.time is None and m.place is None for m in report.mentions)


@pytest.mark.parametrize(
    "text",
    [
        "Heyelanda can kaybı olmadı.",
        "Toprak kaymasında can kaybı yaşanmadı.",
        "Kaya düşmesinde kimse hayatını kaybetmedi.",
    ],
)
def test_explicit_denials_are_not_positive_tolls(text):
    assert tolls(assess(text))
    assert all(c.fact.value == "0" for c in tolls(assess(text)))
    assert all(m.time is None for m in assess(text).mentions)


def test_a_fatality_denial_does_not_supply_physical_onset():
    text = "On 12 October kaya düşmesinde kimse hayatını kaybetmedi."
    report = assess(text)
    assert tolls(report) and all(c.fact.value == "0" for c in tolls(report))
    assert all(m.time is None for m in report.mentions)


@pytest.mark.parametrize(
    "text",
    [
        "Heyelan tatbikatında üç kişinin öldüğü varsayıldı.",
        "Kaya düşmesi simülasyonunda dört kişi hayatını kaybetti.",
    ],
)
def test_simulated_deaths_are_not_observed_fatalities(text):
    report = assess(text)
    assert report.mentions and all(m.role == "forecast" for m in report.mentions)
    assert not tolls(report)


@pytest.mark.parametrize(
    "text",
    ["Heyelanda iki inek öldü.", "Toprak kaymasında üç hayvan hayatını kaybetti."],
)
def test_animal_losses_are_not_human_fatalities(text):
    assert not tolls(assess(text))


@pytest.mark.parametrize(
    "text",
    [
        "Heyelanlarda 12 kişi hayatını kaybetti.",
        "İki heyelanda 12 kişi hayatını kaybetti.",
        "Toprak kaymalarında 12 kişi hayatını kaybetti.",
        "Kaya düşmelerinde 12 kişi hayatını kaybetti.",
        "İki kaya düşmesinde 12 kişi hayatını kaybetti.",
    ],
)
def test_multiple_occurrence_tolls_are_not_allocated_to_one_slide(text):
    report = assess(text)
    claims = tolls(report)
    assert len(claims) == 1
    assert claims[0].fact.value == "Unknown"
    assert "scope unresolved" in claims[0].qualifiers
    assert "combined occurrences" in claims[0].qualifiers
    assert claims[0].excerpt == text


def test_two_victims_or_a_second_slide_is_not_a_two_occurrence_total():
    for text in [
        "Heyelanda iki kişi hayatını kaybetti.",
        "İkinci heyelanda iki kişi hayatını kaybetti.",
    ]:
        assert tolls(assess(text))[0].fact.value == "2"


@pytest.mark.parametrize(
    "text",
    [
        "Heyelanzedelere yardım ulaştırıldı.",
        "Kaya düşmesiz bir yol seçildi.",
        "Siyasi heyelan sonrası bir kişi öldü.",
    ],
)
def test_unlisted_word_prefixes_and_explicit_metaphors_are_not_physical_slides(text):
    assert disasters_in_text(text) == ()
    assert assess(text).eligibility == "unclassified"


def test_actual_slide_survives_a_separate_political_figure_of_speech():
    text = "Heyelanda üç kişi öldü; siyasi heyelan yaşandı."
    assert disasters_in_text(text) == (Disaster.LANDSLIDE,)
    assert any(c.fact.value == "3" for c in tolls(assess(text)))


@pytest.mark.parametrize("action", ["meydana geldi", "oluştu", "yaşandı"])
def test_explicit_slide_occurrence_can_anchor_the_following_death_account(action):
    text = f"Bir heyelan {action}. Bir kişi hayatını kaybetti."
    report = assess(text)
    assert len(tolls(report)) == 1
    assert tolls(report)[0].fact.value == "1"
    assert all(m.role == "reported" for m in report.mentions)
    assert all(m.time is None and m.place is None for m in report.mentions)
