"""Conservative hazard classification for major-news headlines."""

import re

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.hazards.regional_vocabulary import (
    REGIONAL_HAZARDS,
    TURKISH_LANDSLIDE_ENDING,
)
from disaster_monitor.domain.regional_accounts import regional_fatality_account

_NAMED_MOUNTAIN = r"(?-i:(?:Mount|Mt\.?)\s+[A-Z][\w’'-]*(?:\s+[A-Z][\w’'-]*){0,2})"
_VOLCANIC_CONTEXT = r"(?:volcano(?:es|s)?|volcanic|lava|pyroclastic)"
_FIGURATIVE_SUBJECT = (
    r"(?:tributes?|messages?|condolences|congratulations|complaints|applications|"
    r"memories|emails?|calls?)"
)
_NONLITERAL_HAZARDS = re.compile(
    r"\b(?:hurricanes?|typhoons?|cyclones?|tropical storms?)"
    r"[\s\u2010-\u2015-]+(?:force|strength|like)\b|"
    rf"\b{_FIGURATIVE_SUBJECT}\s+flood(?:s|ed|ing)?\s+in\b|"
    rf"\bfloods?\s+of\s+{_FIGURATIVE_SUBJECT}\b|"
    rf"\bflood(?:s|ed|ing)?\s+with\s+{_FIGURATIVE_SUBJECT}\b|"
    r"\briadas?\s+de\s+(?:mensajes|homenajes|cr[ií]ticas|solicitudes|"
    r"condolencias|quejas)\b|"
    rf"\bsiyasi\s+heyelan(?:lar)?{TURKISH_LANDSLIDE_ENDING}\b",
    re.I,
)

_HAZARD_PATTERNS = (
    (Disaster.EARTHQUAKE, re.compile(r"\b(?:earthquakes?|quakes?|seismic)\b", re.I)),
    (
        Disaster.FLOOD,
        re.compile(r"\b(?:floods?|flooding|floodwaters?|inundations?)\b", re.I),
    ),
    (
        Disaster.WILDFIRE,
        re.compile(
            r"\b(?:wildfires?|bushfires?|forest fires?|grass fires?|veld fires?)\b",
            re.I,
        ),
    ),
    (
        Disaster.LANDSLIDE,
        re.compile(r"\b(?:landslides?|mudslides?|rockfalls?)\b", re.I),
    ),
    (Disaster.DROUGHT, re.compile(r"\bdroughts?\b", re.I)),
    (
        Disaster.TROPICAL_CYCLONE,
        re.compile(r"\b(?:hurricanes?|typhoons?|cyclones?|tropical storms?)\b", re.I),
    ),
    (
        Disaster.VOLCANIC_ERUPTION,
        re.compile(
            r"\b(?:volcanic eruptions?|"
            rf"{_VOLCANIC_CONTEXT}[^.!?;\n]{{0,100}}\beruptions?|"
            rf"eruptions?[^.!?;\n]{{0,100}}\b{_VOLCANIC_CONTEXT}|"
            rf"eruptions?\s+of\s+(?:the\s+)?{_NAMED_MOUNTAIN}|"
            rf"(?:volcano|{_NAMED_MOUNTAIN})\s+"
            r"(?:(?:last|has|had|is|was|began|started)\s+){0,2}"
            r"erupt(?:s|ed|ing)?)\b",
            re.I,
        ),
    ),
)
_MAJOR_IMPACT = re.compile(
    r"\b(?:major|catastrophic|deadly|powerful|widespread|emergency|"
    r"evacuat(?:e|es|ed|ion|ions)|kill(?:s|ed)?|dead|deaths?|missing|"
    r"thousands?|hundreds?)\b",
    re.I,
)


def classify_major_disaster_headline(title: str) -> Disaster | None:
    """Return one unambiguous supported hazard with major-impact language."""
    regional = regional_fatality_account(title)
    if not _MAJOR_IMPACT.search(title) and (
        regional is None or regional.value in ("0", "Unknown")
    ):
        return None
    return classify_disaster_text(title)


def classify_disaster_text(title: str) -> Disaster | None:
    """Classify a hazard independently of severity and casualty claims."""
    matches = disasters_in_text(title)
    return matches[0] if len(matches) == 1 else None


def disasters_in_text(text: str) -> tuple[Disaster, ...]:
    """Expose the same hazard vocabulary for conservative source-account scoping."""
    text = _NONLITERAL_HAZARDS.sub(lambda match: " " * len(match[0]), text)
    return tuple(
        disaster
        for disaster, pattern in _HAZARD_PATTERNS
        if pattern.search(text) or REGIONAL_HAZARDS[disaster].search(text)
    )
