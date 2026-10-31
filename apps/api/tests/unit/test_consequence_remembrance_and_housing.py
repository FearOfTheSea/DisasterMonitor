"""Past-hazard remembrance and housing can involve future ceremony or recovery."""

from dataclasses import replace

import pytest

from disaster_monitor.domain.collection import lead_retrieval_priority
from disaster_monitor.domain.news import NewsFeedItem

LEAD = NewsFeedItem(
    "regional", "Local publisher", "Update", "https://local.example/news", None, None
)


@pytest.mark.parametrize(
    "title",
    [
        "Deprem için anma programı düzenlendi",
        "Heyelanda ölenler için anma töreni yapılacak",
        "Depremin anma etkinlikleri başladı",
        "Deprem bölgesinde konutlar hak sahiplerine teslim edildi",
        "Deprem bölgesinde evine dönemeyen kimse kalmayacak",
        "Heyelan sonrasında aileler yeni evlerine kavuştu",
        "Deprem sonrası yeni konutların teslimi bekleniyor",
        "Depremde evini kaybedenlere yeni yuva",
    ],
)
def test_actual_hazard_remembrance_and_recovery_can_be_future_actions(title):
    item = replace(LEAD, title=title)
    assert lead_retrieval_priority(item) >= 2
    assert item.published_at is None


@pytest.mark.parametrize(
    "title",
    [
        "Olası deprem sonrası yeni konut planları açıklandı",
        "Beklenen deprem için anma programı senaryosu hazırlanıyor",
        "Deprem tatbikatında konutlar boşaltılacak",
        "Deprem riski bulunan bölgede yeni konut projesi",
        "Deprem anma programı adlı film gösterime girecek",
        "Yeni konutların teslimi bekleniyor",
        "Heyelan simülasyonu için anma töreni canlandırıldı",
        "Depremden sonra can kaybı olmadı, evlere dönüldü",
    ],
)
def test_drills_fiction_risk_and_zero_death_headlines_do_not_gain_new_lane(title):
    assert lead_retrieval_priority(replace(LEAD, title=title)) < 2
