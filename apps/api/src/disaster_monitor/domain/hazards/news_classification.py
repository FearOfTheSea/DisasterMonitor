"""Conservative hazard classification for major-news headlines."""

import re

from disaster_monitor.domain.disaster_types import Disaster

_HAZARD_PATTERNS = (
    (Disaster.EARTHQUAKE, re.compile(r"\b(?:earthquake|quake|seismic)\b", re.I)),
    (Disaster.FLOOD, re.compile(r"\b(?:flood|flooding|inundation)\b", re.I)),
    (Disaster.WILDFIRE, re.compile(r"\b(?:wildfire|bushfire|forest fire)\b", re.I)),
    (Disaster.LANDSLIDE, re.compile(r"\b(?:landslide|mudslide)\b", re.I)),
    (
        Disaster.TROPICAL_CYCLONE,
        re.compile(r"\b(?:hurricane|typhoon|cyclone|tropical storm)\b", re.I),
    ),
    (
        Disaster.VOLCANIC_ERUPTION,
        re.compile(r"\b(?:volcanic eruption|volcano erupts?|eruption)\b", re.I),
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
    matches = [
        disaster for disaster, pattern in _HAZARD_PATTERNS if pattern.search(title)
    ]
    return matches[0] if len(matches) == 1 else None
