"""Conservative English occurrence roles and date attachment, without I/O."""

import re
from typing import Literal

MentionRole = Literal["reported", "ongoing", "historical", "forecast", "uncertain"]

_PREPARATION = re.compile(
    r"\b(?:risk of|risks? near|forecast|could|may occur|expected to|"
    r"preparedness|preparing|preparations|simulation|drill|warning of|"
    r"ahead of|projected path|should needs arise|on standby)\b",
    re.I,
)
_OCCURRENCE = re.compile(
    r"\b(?:struck|hit|occurred|erupted|killed|died|injured|damaged|destroyed|"
    r"affected|impacted|tore through|displaced|swept|flooded|triggered|"
    r"strengthened|intensifies|"
    r"has moved|brought|bringing|began|started|onset|reported|recorded|"
    r"following|after|survived|survivors|flood-affected)\b",
    re.I,
)
_ONGOING = re.compile(
    r"\b(?:(?:flood(?:s|ing)?|drought|wildfires?|eruption|earthquake activity)\s+"
    r"(?:continues?|persists?)|ongoing\s+(?:flood|drought|wildfire|eruption)|"
    r"remain flooded)\b",
    re.I,
)
_ACTIVITY = re.compile(
    r"\b(?:treated|treating|clinic|patients|medical care|assessment|"
    r"response|publication|published|updated|mission|declared|arrived|"
    r"distributed|dispatched|as of|until)\b",
    re.I,
)


def occurrence_role(text: str, *, historical: bool = False) -> MentionRole:
    if historical:
        return "historical"
    if _PREPARATION.search(text):
        return "forecast"
    if _ONGOING.search(text):
        return "ongoing"
    if _OCCURRENCE.search(text):
        return "reported"
    return "uncertain"


def date_is_occurrence(text: str, start: int, end: int) -> bool:
    """Require local occurrence language; exclude datelines and activity clocks."""
    before = text[:start]
    after = text[end:]
    # Scope at sentence/semicolon boundaries, allowing a leading dateline dash.
    left = re.split(r"[!?;]|[.](?=\s)|[–—]", before)[-1]
    right = re.split(r"[!?;]|[.](?=\s)|[–—]", after)[0]
    context = left + " " + right
    if re.search(
        r"\b(?:strengthened|intensified|weakened|downgraded)\b", context, re.I
    ):
        return False  # A storm phase update does not establish impact onset.
    if _PREPARATION.search(context):
        return False
    if re.search(r"\b(?:as of|until|through|reported on|issued on)\s*$", left, re.I):
        return False
    # An explicit 'on DATE' adjacent to a hazard occurrence wins over a different
    # activity date elsewhere in the sentence. Otherwise activity clocks fail closed.
    if _ACTIVITY.search(left[-100:]):
        return False
    if not left.strip() or re.fullmatch(r"\s*(?:On|From|Since|Between)\s*", left, re.I):
        return bool(_OCCURRENCE.search(right)) and not _ACTIVITY.search(right)
    if re.search(r"\b(?:on|from|since|between)\s*$", left, re.I):
        return bool(_OCCURRENCE.search(context)) and not _ACTIVITY.search(context)
    return bool(_OCCURRENCE.search(context)) and not _ACTIVITY.search(context)
