"""Metadata strength changes retrieval order, never publisher evidence admission."""

import re

from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.mention_occurrence import occurrence_role
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.domain.regional_accounts import (
    regional_competing_cause,
    regional_fatality_account,
)
from disaster_monitor.domain.reported_impacts import (
    fatality_analysis_text,
    only_nonhuman_deaths,
)
from disaster_monitor.domain.source_sentences import source_sentences

_CONSEQUENCE_HINT = re.compile(
    r"\b(?:survivors?|memorials?|anniversar\w*|remembr\w*|bereaved|"
    r"resettl\w*|rehabilitat\w*|disaster declaration|state of emergency)\b",
    re.I,
)


# These are retrieval hints only. Literal supported hazard context is still needed.
_TURKISH_CONSEQUENCE_HINT = re.compile(
    r"\b(?:yıl\s*dönüm\w*|yakınlarını\s+kaybeden\w*|"
    r"sağ\s+kurtul(?:an|du)\w*|anıl(?:dı|ıyor|acak)(?:lar)?|"
    r"anma(?:sı(?:nda|na)?|ya)?|"
    r"(?:üzerinden|aradan)\s+\d+\s+yıl\s+geç\w*|"
    r"(?:\d+|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)\s+yıl\s+sonra|"
    r"yıllar\s+sonra|kalıcı\s+konut\w*|yeniden\s+(?:inşa|yerleş\w*))\b",
    re.I,
)
_TURKISH_HOUSING_RECOVERY = re.compile(
    r"\b(?:bölgesin\w*|sonras[ıi](?:nda)?|ardından)\b.{0,120}"
    r"\b(?:ev(?:in\w*|ler\w*)?|konut\w*|yuva\w*)\b"
    r"|\bev(?:in\w*|ler\w*)\s+kaybeden\w*\b",
    re.I,
)
_TURKISH_NONOCCURRENCE = re.compile(
    r"\b(?:tatbikat\w*|simülasyon\w*|senaryo\w*|varsayım\w*|"
    r"(?:olası|beklenen)\s+(?:deprem\w*|heyelan\w*|sel\w*|yangın\w*)|"
    r"risk(?:i|ine|li)\w*|"
    r"hayatını\s+kaybeden(?:ler)?\s+(?:olmadı|yok)|"
    r"can\s+kaybı\s+(?:olmadı|yaşanmadı|yok)|hayatını\s+kaybetmedi|ölmedi|"
    r"(?:adlı|isimli)\s+(?:oyun\w*|film\w*|roman\w*))\b",
    re.I,
)

_FATALITY_HINT = re.compile(
    r"\b(?:kill(?:ed|s)?|dead(?:ly)?|died|dies?|drowned|deaths?|fatalities|fatal)\b",
    re.I,
)
_NO_FATALITY_HINT = re.compile(
    r"\b(?:no|zero|without)(?:\s+(?:one|people|reported|confirmed|known))*\s+"
    r"(?:deaths?|fatalities|casualties|killed|dead(?:ly)?|drowned)\b"
    r"|\bnot\s+deadly\b",
    re.I,
)
_SPECIFIC_DEATH = re.compile(r"\b(?:kill(?:ed|s)?|died|dies|drowned)\b", re.I)
_SURVIVAL_ACCOUNT = re.compile(
    r"\b(?:none (?:of them )?survived|no survivors|"
    r"lost (?:his|her|their) li(?:fe|ves)|"
    r"claim(?:ed|s)? (?:\w+\s+){0,4}lives)\b",
    re.I,
)
_UNCERTAIN_ACCOUNT = re.compile(
    r"\b(?:if|may|might|could|would|will|risk|fear(?:s|ed)?|warn(?:s|ed)?|"
    r"expected|predicted|forecast)\b",
    re.I,
)


def _has_fatality_hint(text: str) -> bool:
    hint = fatality_analysis_text(text)
    regional = regional_fatality_account(hint)
    return bool(_FATALITY_HINT.search(hint) and not _NO_FATALITY_HINT.search(hint)) or (
        regional is not None
        and (
            regional.value not in ("0", "Unknown")
            or "scope unresolved" in regional.qualifiers
        )
    )


def _specific_disaster_account(text: str) -> bool:
    # Requiring hazard context in the same source sentence prevents a hazard
    # headline from lending context to an unrelated fatality in a sidebar.
    for sentence in source_sentences(text):
        hint = fatality_analysis_text(sentence)
        if (
            not disasters_in_text(hint)
            or _NO_FATALITY_HINT.search(hint)
            or _UNCERTAIN_ACCOUNT.search(hint)
            or only_nonhuman_deaths(hint)
            or regional_competing_cause(hint)
        ):
            continue
        regional = regional_fatality_account(hint)
        if regional is not None and regional.value not in ("0", "Unknown"):
            return True
        if _SPECIFIC_DEATH.search(hint) or _SURVIVAL_ACCOUNT.search(hint):
            return True
    return False


def _consequence_headline(text: str) -> bool:
    if (
        not disasters_in_text(text)
        or _NO_FATALITY_HINT.search(text)
        or occurrence_role(text) == "forecast"
    ):
        return False
    if _CONSEQUENCE_HINT.search(text):
        return True
    return bool(
        (
            _TURKISH_CONSEQUENCE_HINT.search(text)
            or _TURKISH_HOUSING_RECOVERY.search(text)
        )
        and not _TURKISH_NONOCCURRENCE.search(text)
    )


def lead_retrieval_priority(lead: NewsFeedItem) -> int:
    """Inspect specific casualty and consequence context before weak themes."""
    headlines = dict.fromkeys((lead.title, lead.search_title or ""))
    if any(_has_fatality_hint(t) for t in headlines if t):
        return 3
    # Recovery and retrospective reporting can carry fatality context only in
    # the body. This is an inspection hint, never a casualty or event claim.
    if any(_consequence_headline(t) for t in headlines if t):
        return 2
    if not lead.discovery_hint:
        return 0
    if _specific_disaster_account(lead.discovery_hint):
        return 2
    return int(
        _has_fatality_hint(
            f"{lead.title} {lead.search_title or ''} {lead.discovery_hint}"
        )
    )


def preferred_retrieval_priority(requests_used: int) -> int | None:
    """Give consequence reporting one in five opportunities within the same cap.

    Other opportunities retain normal priority order. When no preferred work is
    ready, the journal can use the opportunity for other reporting.
    """
    return 2 if requests_used % 5 == 4 else None
