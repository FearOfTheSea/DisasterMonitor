"""Conservative hazard classification for major-news headlines."""

import re

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.hazards.regional_vocabulary import REGIONAL_HAZARDS
from disaster_monitor.domain.regional_accounts import regional_fatality_account

_HAZARD_PATTERNS = (
    (Disaster.EARTHQUAKE, re.compile(r"\b(?:earthquakes?|quakes?|seismic)\b", re.I)),
    (Disaster.FLOOD, re.compile(r"\b(?:floods?|flooding|inundations?)\b", re.I)),
    (
        Disaster.WILDFIRE,
        re.compile(r"\b(?:wildfires?|bushfires?|forest fires?|grass fires?)\b", re.I),
    ),
    (Disaster.LANDSLIDE, re.compile(r"\b(?:landslides?|mudslides?)\b", re.I)),
    (Disaster.DROUGHT, re.compile(r"\bdroughts?\b", re.I)),
    (
        Disaster.TROPICAL_CYCLONE,
        re.compile(r"\b(?:hurricanes?|typhoons?|cyclones?|tropical storms?)\b", re.I),
    ),
    (
        Disaster.VOLCANIC_ERUPTION,
        re.compile(
            r"\b(?:volcanic eruptions?|eruptions?|"
            r"(?:volcano|(?-i:Mount|Mt\.)\s+[A-Z][\w’'-]*"
            r"(?:\s+[A-Z][\w’'-]*){0,2})\s+"
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
    return tuple(
        disaster
        for disaster, pattern in _HAZARD_PATTERNS
        if pattern.search(text) or REGIONAL_HAZARDS[disaster].search(text)
    )
