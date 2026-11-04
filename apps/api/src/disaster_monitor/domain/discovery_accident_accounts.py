"""Keep independent accident accounts out of a neighbouring hazard's toll."""

import re

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.hazards.news_classification import disasters_in_text

_ACCIDENT = re.compile(r"\b(?:crash(?:es)?|collisions?|wrecks?|accidents?)\b", re.I)
_FATAL = re.compile(r"\b(?:kill(?:ed|s)?|died|dies?|dead|deaths?|fatalities)\b", re.I)
_BOUNDARY = re.compile(r",\s*(?:and|while|whereas|but)\s+", re.I)
_CONJUNCTION = re.compile(r"\b(?:and|or)\b", re.I)
_CAUSAL_CONTEXT = re.compile(
    r"\b(?:caused|triggered|sparked|led to|resulted in|due to|because of|"
    r"during|after|fleeing|following)\b",
    re.I,
)


def scoped_accident_account(text: str, disaster: Disaster) -> str:
    """Scope structured totals only; the original source remains retained.

    Two independent clauses can supply separate accounts. An explicit hazard
    link to the accident remains available, including uncertain source wording.
    A shared flood/accident toll cannot establish either cause's own count.
    """
    parts = _BOUNDARY.split(text)
    if len(parts) == 2:
        for accident, hazard in (parts, parts[::-1]):
            if (
                _ACCIDENT.search(accident)
                and _FATAL.search(accident)
                and disaster not in disasters_in_text(accident)
                and disaster in disasters_in_text(hazard)
                and not _ACCIDENT.search(hazard)
            ):
                return hazard.strip()
    if fatal := _FATAL.search(text):
        # Shared subjects precede the predicate; shared causes can follow it.
        # Causal/temporal links are not a coordinated independent accident list.
        for causes in (text[: fatal.start()], text[fatal.end() :]):
            if (
                _ACCIDENT.search(causes)
                and disaster in disasters_in_text(causes)
                and _CONJUNCTION.search(causes)
                and not _CAUSAL_CONTEXT.search(causes)
            ):
                return ""
    return text
