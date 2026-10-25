"""Literal Turkish earthquake accounts keep source wording and episode scope."""

from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.domain.reported_impacts import extract_reported_impacts

NOW = datetime(2026, 10, 24, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Yerel haber", "https://daily.example/story", NOW, None, NOW
)


@pytest.mark.parametrize(
    "word",
    [
        "deprem",
        "depremde",
        "depremi",
        "depremin",
        "depreminde",
        "depreminin",
        "depremler",
        "depremlerde",
        "depremlerinde",
        "depremlerinin",
    ],
)
def test_literal_earthquake_suffixes_share_one_hazard(word):
    assert disasters_in_text(word) == (Disaster.EARTHQUAKE,)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Depremde üç kişi hayatını kaybetti.", "3"),
        ("Depremde 12 kişinin öldüğü bildirildi.", "12"),
        ("Depremde hayatını kaybeden dört kişi anıldı.", "4"),
        ("Depremde bir çocuk öldü.", "1"),
        ("Depremde yüzlerce kişinin öldüğü bildirildi.", "Reported; count unknown"),
        ("Depremde bir işçi yaşamını yitirdi.", "1"),
        ("Depremde can kaybı olduğu bildirildi.", "Reported; count unknown"),
        ("İki kişinin öldüğü depremde yardım çalışmaları sürdü.", "2"),
        ("DEPREMDE ALTI KİŞİ HAYATINI KAYBETTİ.", "6"),
    ],
)
def test_attributed_human_deaths_are_accessible_without_invented_onset(text, value):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.eligibility == "eligible"
    claims = [
        c for m in report.mentions for c in m.claims if c.fact.category == "fatalities"
    ]
    assert len(claims) == 1
    assert claims[0].fact.value == value
    assert claims[0].excerpt == text
    assert claims[0].fact.source == SOURCE
    assert all(m.time is None for m in report.mentions)
    assert report.article.text == text


@pytest.mark.parametrize(
    "text",
    [
        "Depremde can kaybı olmadı.",
        "Depremde can kaybı yaşanmadı.",
        "Depremde hayatını kaybeden olmadı.",
        "Depremde kimse hayatını kaybetmedi.",
    ],
)
def test_explicit_denials_do_not_become_positive_tolls(text):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "0"


@pytest.mark.parametrize(
    "text",
    [
        "Depremde 47 yaşındaki kişi öldü.",
        "Depremde hayatını kaybeden 47 yaşındaki kişi anıldı.",
    ],
)
def test_an_age_is_not_a_death_count(text):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "Reported; count unknown"


@pytest.mark.parametrize(
    "text",
    [
        "Deprem tatbikatında üç kişinin öldüğü varsayıldı.",
        "Deprem simülasyonunda dört kişi hayatını kaybetti.",
    ],
)
def test_drill_and_simulation_accounts_do_not_become_observed_deaths(text):
    report = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert report.mentions and all(m.role == "forecast" for m in report.mentions)
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


@pytest.mark.parametrize(
    "text",
    [
        "Depremde iki inek öldü.",
        "Depremde üç hayvan hayatını kaybetti.",
    ],
)
def test_explicit_animal_losses_do_not_become_human_deaths(text):
    assert not extract_reported_impacts(text, SOURCE)


@pytest.mark.parametrize(
    "text",
    [
        "Depremlerde 800 kişi hayatını kaybetti.",
        "İki depremde 800 kişi hayatını kaybetti.",
        "Depremleri hatırlatarak 800 kişinin öldüğü belirtildi.",
        "İki büyük depremde 800 kişi hayatını kaybetti.",
    ],
)
def test_multiple_earthquake_tolls_cannot_be_allocated_to_one_occurrence(text):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers
    assert "combined occurrences" in claim.qualifiers
    assert claim.excerpt == text


@pytest.mark.parametrize(
    "text",
    [
        "Depremzedelere yardım ulaştırıldı.",
        "Deprembilimciler yeni araştırmayı yayımladı.",
    ],
)
def test_a_lexical_prefix_does_not_match_unlisted_words(text):
    assert not disasters_in_text(text)


def test_a_separate_armed_attack_toll_is_not_allocated_to_an_earthquake():
    report = assess_article(
        DiscoveryArticle(
            SOURCE, "Deprem bölgeyi etkiledi, ancak silahlı saldırıda iki kişi öldü."
        ),
        ReportingInterval.at_start(3, NOW),
    )
    assert report.mentions
    assert not any(
        c.fact.category == "fatalities" for m in report.mentions for c in m.claims
    )


def test_an_unknown_toll_stays_unknown():
    (claim,) = extract_reported_impacts("Depremde can kaybı bilinmiyor.", SOURCE)
    assert claim.fact.value == "Unknown"


@pytest.mark.parametrize(
    "text",
    [
        "Depremde kimse ölmedi, ancak başka bir yerde iki kişi öldü.",
        "No hubo muertos en Riverton, pero dos personas murieron en Lakeview.",
    ],
)
def test_a_local_denial_does_not_override_another_positive_account(text):
    (claim,) = extract_reported_impacts(text, SOURCE)
    assert claim.fact.value == "Unknown"
    assert "scope unresolved" in claim.qualifiers


@pytest.mark.parametrize(
    ("title", "priority"),
    [
        ("Depremlerde 800 kişi hayatını kaybetti", 2),
        ("Depremde can kaybı olmadı", 0),
    ],
)
def test_a_combined_fatal_headline_is_a_retrieval_hint_without_claim_admission(
    title, priority
):
    lead = NewsFeedItem("lead", "Daily", title, SOURCE.canonical_url, None, None, NOW)
    assert lead_retrieval_priority(lead) == priority
    assert lead.published_at is None
