"""Literal regional wording exposes source context without translating its facts."""

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

NOW = datetime(2026, 11, 4, tzinfo=UTC)
SOURCE = SourceReference(
    "news", "Daily", "Report", "https://daily.example/report", NOW, None, NOW
)


@pytest.mark.parametrize(
    ("text", "hazard"),
    [
        ("河川が氾濫し、農地に被害が出ました。", Disaster.FLOOD),
        ("洪水の被害について調べています。", Disaster.FLOOD),
        ("台風が接近しています。", Disaster.TROPICAL_CYCLONE),
        ("道路发生山体崩塌，救援正在进行。", Disaster.LANDSLIDE),
        ("车辆被落石击中。", Disaster.LANDSLIDE),
        ("发生泥石流后道路中断。", Disaster.LANDSLIDE),
        ("เกิดเหตุดินโคลนถล่มในพื้นที่", Disaster.LANDSLIDE),
        ("ชาวบ้านหนีดินถล่ม", Disaster.LANDSLIDE),
        ("Um incêndio no pasto atingiu a propriedade.", Disaster.WILDFIRE),
        ("Os bombeiros combateram fogo em área de vegetação.", Disaster.WILDFIRE),
        ("O incêndio atingiu uma área de pastagem.", Disaster.WILDFIRE),
        ("Incêndios florestais atingiram a região.", Disaster.WILDFIRE),
        ("O alagamento bloqueou a rua.", Disaster.FLOOD),
        ("O transbordamento de um córrego atingiu a rua.", Disaster.FLOOD),
        ("Un éboulement dans une mine a enseveli un ouvrier.", Disaster.LANDSLIDE),
    ],
)
def test_literal_wording_opens_the_unchanged_report_without_inventing_fields(
    text, hazard
):
    assert disasters_in_text(text) == (hazard,)
    result = assess_article(
        DiscoveryArticle(SOURCE, text), ReportingInterval.at_start(3, NOW)
    )
    assert result.article.text == text
    assert result.mentions
    assert all(m.disaster == hazard for m in result.mentions)
    assert all(m.time is None and m.place is None for m in result.mentions)
    assert not any(
        c.fact.category == "fatalities" and c.fact.value not in ("0", "Unknown")
        for m in result.mentions
        for c in m.claims
    )


@pytest.mark.parametrize(
    "text",
    [
        "Um incêndio na cozinha destruiu a casa.",
        "O fogo no motor do carro foi apagado.",
        "A vegetação perto da casa não queimou.",
        "A economia está em fogo.",
        "O pastoreio foi retomado após o incêndio doméstico.",
        "O transbordamento de uma panela causou queimaduras.",
        "大楼发生崩塌。",  # A building collapse does not establish mass movement.
        "洪水のようなメールが届いた。",  # A figurative flood of email.
        "Un effondrement du bâtiment a blessé deux personnes.",
    ],
)
def test_other_fire_collapse_and_figurative_context_do_not_gain_a_hazard(text):
    assert not disasters_in_text(text)
