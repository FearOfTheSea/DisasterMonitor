"""Conservative hazard classification for major-news headlines."""

import re

from disaster_monitor.domain.disaster_types import Disaster

_HAZARD_PATTERNS = (
    (Disaster.EARTHQUAKE, re.compile(r"\b(?:earthquakes?|quakes?|seismic)\b", re.I)),
    (Disaster.FLOOD, re.compile(r"\b(?:floods?|flooding|inundations?)\b", re.I)),
    (
        Disaster.WILDFIRE,
        re.compile(r"\b(?:wildfires?|bushfires?|forest fires?)\b", re.I),
    ),
    (Disaster.LANDSLIDE, re.compile(r"\b(?:landslides?|mudslides?)\b", re.I)),
    (Disaster.DROUGHT, re.compile(r"\bdroughts?\b", re.I)),
    (
        Disaster.TROPICAL_CYCLONE,
        re.compile(r"\b(?:hurricanes?|typhoons?|cyclones?|tropical storms?)\b", re.I),
    ),
    (
        Disaster.VOLCANIC_ERUPTION,
        re.compile(r"\b(?:volcanic eruptions?|volcano erupts?|eruptions?)\b", re.I),
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
    if not _MAJOR_IMPACT.search(title):
        return None
    return classify_disaster_text(title)


def classify_disaster_text(title: str) -> Disaster | None:
    """Classify a hazard independently of severity and casualty claims."""
    matches = disasters_in_text(title)
    return matches[0] if len(matches) == 1 else None


def disasters_in_text(text: str) -> tuple[Disaster, ...]:
    """Expose the same hazard vocabulary for conservative source-account scoping."""
    return tuple(
        disaster for disaster, pattern in _HAZARD_PATTERNS if pattern.search(text)
    )
