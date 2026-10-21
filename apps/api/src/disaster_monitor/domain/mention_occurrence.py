"""Conservative English occurrence roles and date attachment, without I/O."""

import re
from typing import Literal

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.source_sentences import source_clauses

MentionRole = Literal["reported", "ongoing", "historical", "forecast", "uncertain"]

_PREPARATION = re.compile(
    r"\b(?:risk of|risks? near|forecast|could|may occur|"
    r"expected\s+(?:to|in|across|near|over|on)|"
    r"preparedness|preparing|preparations|simulation|drill|warning of|"
    r"ahead of|projected path|should needs arise|on standby|"
    r"(?:may|might|will)\s+(?:\w+\s+){0,2}(?:hit|strike|occur|cause|trigger))\b",
    re.I,
)
_OCCURRENCE = re.compile(
    r"\b(?:struck|hit|occurred|erupted|killed|died|injured|damaged|destroyed|"
    r"affected|impacted|tore through|displaced|swept|flooded|triggered|caused|"
    r"devastated|strengthened|intensifies|"
    r"has moved|brought|bringing|began|started|onset|reported|recorded|"
    r"ignited|spread|burned|burnt|observed|"
    r"(?:left|leaves)\s+(?:\w+\s+){0,5}dead|"
    r"survived|survivors)\b",
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
_RESPONSE_CONTEXT = re.compile(
    r"\b(?:patients?|clinic|medical|physician|deployment|relief|"
    r"response|responding|recovery|aid|treatment)\b",
    re.I,
)
_PHYSICAL_OCCURRENCE = re.compile(
    r"\b(?:floods?|flooding|earthquakes?|wildfires?|fires?|landslides?|"
    r"tsunamis?|drought|eruption|hurricane|typhoon|cyclone)\s+"
    r"(?:\w+\s+){0,2}(?:struck|hit|occurred|erupted|killed|damaged|"
    r"destroyed|swept|flooded|triggered|devastated|cut off|tore through)\b",
    re.I,
)
_FELT_EXTENT = re.compile(r"\b(?:was|were)\s+(?:also\s+)?felt\b", re.I)
_DIRECT_IMPACT = re.compile(
    r"\b(?:killed|died|injured|damaged|destroyed|collapsed|displaced)\b", re.I
)
_STATEMENT = re.compile(
    r"\b(?:said|says?|told|announced|confirmed|reported|explained|added|"
    r"warned|disclosed|stated)\b",
    re.I,
)


def _victim_firefighting_start(text: str) -> int | None:
    if (
        not re.search(
            r"\b(?:victims|casualties)\s+(?:were|had been)\s+"
            r"(?:among|battling|fighting|trying|attempting)\b",
            text,
            re.I,
        )
        or _PREPARATION.search(text)
        or _ACTIVITY.search(text)
        or re.search(r"\b(?:will|would|may|might|could|not|never)\b", text, re.I)
        or disasters_in_text(text) != (Disaster.WILDFIRE,)
    ):
        return None
    for action in re.finditer(
        r"\b(?:battling|fighting|(?:trying|attempting)\s+to\s+contain)\s+",
        text,
        re.I,
    ):
        object_text = re.match(
            r"(?:(?:a|an|the)\s+)?[\w'-]+(?:\s+[\w'-]+)?",
            text[action.end() :],
            re.I,
        )
        if object_text and disasters_in_text(object_text[0]) == (Disaster.WILDFIRE,):
            return action.start()
    return None


def is_victim_firefighting_activity(text: str) -> bool:
    """A past, hazard-specific activity of the source's victims, not ignition."""
    return _victim_firefighting_start(text) is not None


def victim_activity_date_requires_reference(text: str) -> bool:
    return not _PHYSICAL_OCCURRENCE.search(text) and is_victim_firefighting_activity(
        text
    )


def _occurrence_start(text: str) -> int | None:
    direct = _OCCURRENCE.search(text)
    starts = [direct.start()] if direct else []
    victim_activity = _victim_firefighting_start(text)
    if victim_activity is not None:
        starts.append(victim_activity)
    return min(starts, default=None)


def is_felt_extent(text: str) -> bool:
    """Felt/reported shaking describes reach, without allocating human impacts."""
    return bool(_FELT_EXTENT.search(text)) and not _DIRECT_IMPACT.search(text)


def has_individual_aftershock(text: str) -> bool:
    return bool(
        re.search(r"\b(?:a|an|another|new)\s+(?:\w+\s+){0,2}aftershock\b", text, re.I)
    )


def occurrence_detail(text: str) -> str | None:
    magnitude = re.search(r"(?:magnitude[-\s]+\d\.\d|\d\.\d[- ]magnitude)", text, re.I)
    if magnitude:
        return magnitude[0]
    return "aftershock" if has_individual_aftershock(text) else None


def reported_magnitude(detail: str | None) -> str | None:
    match = re.search(r"\d\.\d", detail or "")
    return match[0] if match else None


def same_occurrence_detail(first: str, other: str) -> bool:
    if first.casefold() == other.casefold():
        return True
    magnitude = reported_magnitude(first)
    return magnitude is not None and magnitude == reported_magnitude(other)


def local_impact_context(text: str) -> str:
    """Keep direct impact clauses separate from a preceding felt-area account."""
    if not _FELT_EXTENT.search(text):
        return text
    clauses = re.split(r"\b(?:and|but|while|whereas)\b", text, flags=re.I)
    impacts = [clause for clause in clauses if _DIRECT_IMPACT.search(clause)]
    return impacts[0] if len(impacts) == 1 else text


def is_response_context(text: str) -> bool:
    return bool(_RESPONSE_CONTEXT.search(text))


def occurrence_years(text: str) -> tuple[int, ...]:
    """Bare years require a local physical occurrence, not a recordkeeping baseline."""
    years = []
    for match in re.finditer(r"\b(?:in|during) ((?:19|20)\d{2})\b", text, re.I):
        before = re.split(r"[,;.!?]", text[: match.start()])[-1]
        after = re.split(r"[,;.!?]", text[match.end() :].lstrip(" ,"))[0]
        if (
            _PHYSICAL_OCCURRENCE.search(before)
            or _PHYSICAL_OCCURRENCE.search(after)
            or is_victim_firefighting_activity(text)
        ):
            years.append(int(match[1]))
    return tuple(years)


def has_distinct_occurrence(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:another|separate|different|new)\s+(?:[\w.-]+\s+){0,2}"
            r"(?:flood|earthquake|wildfire|fire|landslide|tsunami|drought|"
            r"eruption|hurricane|typhoon|cyclone)\b",
            text,
            re.I,
        )
    )


def occurrence_role(text: str, *, historical: bool = False) -> MentionRole:
    if historical:
        return "historical"
    if _PREPARATION.search(text):
        return "forecast"
    if _ONGOING.search(text):
        return "ongoing"
    if (
        is_response_context(text)
        and not _PHYSICAL_OCCURRENCE.search(text)
        and not re.search(
            r"\b(?:killed|died|injured|destroyed|collapsed)\b", text, re.I
        )
    ):
        return "uncertain"
    if _occurrence_start(text) is not None:
        return "reported"
    return "uncertain"


def date_is_occurrence(text: str, start: int, end: int) -> bool:
    """Require local occurrence language; exclude datelines and activity clocks."""
    before = text[:start]
    after = text[end:]
    # Scope at sentence/semicolon boundaries, allowing a leading dateline dash.
    left = source_clauses(before)[-1]
    right = source_clauses(after)[0]
    context = left + " " + right
    possessive = bool(re.match(r"[’']s\b", right))
    statements = list(_STATEMENT.finditer(left))
    if statements and not possessive:
        statement_tail = left[statements[-1].end() :]
        direct_quote = re.search(
            r"[\s,:][\"'“‘]\s*(?:(?:On|From|Since|Between)\s+)?$",
            statement_tail,
            re.I,
        )
        if not direct_quote and _occurrence_start(statement_tail) is None:
            return False  # Dates the statement, without a subsequent physical action.
    if not possessive and (
        not left.strip() or re.fullmatch(r"\s*(?:On|From|Since|Between)\s*", left, re.I)
    ):
        statement = _STATEMENT.search(right)
        occurrence = _occurrence_start(right)
        if statement and (occurrence is None or statement.start() <= occurrence):
            return False
    if re.search(
        r"\b(?:photo|photograph|photographed|pictured|caption)\b", context, re.I
    ):
        return False
    if re.search(
        r"\b(?:strengthened|intensified|weakened|downgraded)\b", context, re.I
    ):
        return False  # A storm phase update does not establish impact onset.
    if _PREPARATION.search(context):
        return False
    if re.search(r"\b(?:as of|by|until|through|reported on|issued on)\s*$", left, re.I):
        return False
    # An explicit 'on DATE' adjacent to a hazard occurrence wins over a different
    # activity date elsewhere in the sentence. Otherwise activity clocks fail closed.
    if _ACTIVITY.search(left[-100:]):
        return False
    if not left.strip() or re.fullmatch(r"\s*(?:On|From|Since|Between)\s*", left, re.I):
        return _occurrence_start(right) is not None and not _ACTIVITY.search(right)
    if re.search(r"\b(?:on|from|since|between)\s*$", left, re.I):
        return _occurrence_start(context) is not None and not _ACTIVITY.search(context)
    return _occurrence_start(context) is not None and not _ACTIVITY.search(context)
