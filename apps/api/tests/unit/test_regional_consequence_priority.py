"""Literal Turkish recovery metadata gets inspection, never invented event facts."""

from dataclasses import replace

import pytest

from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.news import NewsFeedItem

LEAD = NewsFeedItem(
    "regional",
    "Local newspaper",
    "Local update",
    "https://local.example/news",
    None,
    None,
)


@pytest.mark.parametrize(
    "title",
    [
        "Depremin yıl dönümünde aileler bir araya geldi",
        "Depremde yakınlarını kaybeden aileler o günü unutamıyor",
        "Depremden sağ kurtulanlar yeni evlerine taşındı",
        "Heyelanın ardından sağ kurtulanlar deneyimlerini anlattı",
        "Depremde hayatını kaybedenler törenle anıldı",
        "Heyelanda yaşamını yitirenler anılıyor",
        "Depremin üzerinden 42 yıl geçti",
        "Depremden dokuz yıl sonra mahalle yeniden inşa ediliyor",
        "Deprem sonrası kalıcı konutlar ailelere teslim edildi",
        "Deprem sonrası yeniden yerleşim çalışmaları başladı",
        "Heyelan sonrasında yeniden inşa çalışmaları tamamlandı",
        "Depremden yıllar sonra yaralar sarılıyor",
    ],
)
def test_turkish_consequences_enter_inspection_lane_without_claiming_deaths(title):
    item = replace(LEAD, title=title)
    before = replace(item)
    assert lead_retrieval_priority(item) == 2
    assert item == before
    assert item.published_at is None


@pytest.mark.parametrize(
    "title",
    [
        "Deprem tatbikatında yakınlarını kaybeden aileler canlandırıldı",
        "Deprem simülasyonunun yıl dönümü kutlandı",
        "Olası deprem sonrası yeniden inşa planı tanıtıldı",
        "Depremde hayatını kaybeden olmadı",
        "Depremde can kaybı yaşanmadı; konutlar yeniden inşa edilecek",
        "Deprem adlı oyunun yıl dönümü kutlandı",
        "Yıl dönümü töreni yapıldı",
        "Heyelan riski için hazırlık toplantısı yapıldı",
        "Deprem risk haritası açıklandı",
        "Hayvanat bahçesindeki hayvanlar için anıt yapıldı",
        "Deprem tatbikatı için kalıcı konutlar modeli hazırlanıyor",
    ],
)
def test_nonliteral_hypothetical_absent_deaths_and_unrelated_headlines_stay_weak(title):
    assert lead_retrieval_priority(replace(LEAD, title=title)) == 0


def test_original_search_title_can_supply_consequence_context():
    item = replace(
        LEAD,
        search_title="Heyelanın yıl dönümünde aileler bir araya geldi",
        discovery_hint="Publisher copyright notice",
    )
    assert lead_retrieval_priority(item) == 2


def test_a_broad_index_hint_does_not_invent_a_consequence_headline():
    item = replace(
        LEAD, discovery_hint="Depremin yıl dönümünde aileler bir araya geldi"
    )
    assert lead_retrieval_priority(item) == 0


def test_direct_fatality_keeps_its_existing_higher_priority():
    item = replace(LEAD, title="Earthquake killed six people")
    assert lead_retrieval_priority(item) == 3
