"""Bound attributed disaster accounts inside potentially multi-topic reporting.

These are bounded literal language rules, not semantic causal verification. Original
report text and links remain retained even when an account cannot be safely scoped.
"""

import re

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.regional_accounts import (
    has_regional_weather_toll,
    regional_competing_cause,
)
from disaster_monitor.domain.source_sentences import source_sentences

_OTHER_CAUSE = re.compile(
    r"\b(?:conflict|violence|cholera|ebola|measles|covid-?19|war|warfare|"
    r"airstrikes?|bombing|gunfire|shootings?|armed attacks?|"
    r"chronic conditions?|diabetes|hypertension|COPD)\b",
    re.I,
)
_DATED_FAMINE_WORDING = r"(?:\d{4}\s+famines?|famines?\s+(?:of|in)\s+\d{4})"
_DATED_FAMINE = re.compile(rf"\b{_DATED_FAMINE_WORDING}\b", re.I)
_DROUGHT_FAMINE_LINK = re.compile(
    rf"\bdrought\s+(?:caused|triggered|led to|brought on|resulted in)\s+"
    rf"(?:(?:the|a)\s+)?{_DATED_FAMINE_WORDING}\b|"
    rf"\bdrought[-\s]+(?:induced|driven|caused)[-\s]+{_DATED_FAMINE_WORDING}\b|"
    rf"\b{_DATED_FAMINE_WORDING},?\s+(?:(?:was|had been)\s+)?"
    r"(?:(?:caused|triggered|driven)\s+by|due to|because of)\s+"
    r"(?:the\s+)?drought\b",
    re.I,
)
_FATAL_FIRE_IGNITION_ACCIDENT = re.compile(
    r"\b(?:crash|collision|wreck)\b[^.!?;\n]{0,140}"
    r"\b(?:kill(?:ed|s)|left[^.!?;\n]{0,40}\bdead)\b"
    r"[^.!?;\n]{0,80}\band\s+(?:(?:also|then|later)\s+)?"
    r"(?:spark(?:ed|s)|ignit(?:ed|es)|start(?:ed|s)|trigger(?:ed|s))\b"
    r"[^.!?;\n]{0,45}\b(?P<fire>wildfires?|bushfires?|forest fires?|grass fires?)\b",
    re.I,
)
_RECOLLECTION_COMPARISON = re.compile(
    r"\b(?:y\s+que\s+(?:me|te|se|nos|os)\s+acuerd(?:e|es|en)\s+de|"
    r"(?:lo\s+que|y\s+esto)\s+(?:(?:me|te|nos|les)\s+)?recuerda\s+a|"
    r"(?:which|and\s+this)\s+remind(?:s|ed)?\s+"
    r"(?:me|you|him|her|us|them)\s+of)\b",
    re.I,
)


def _recollection_account(text: str, disaster: Disaster) -> str:
    """Scope a literal recollection without transferring the other clause's toll.

    This does not assert which event the unqualified account describes. When the
    same hazard occurs on both sides, the existing unresolved-total rules apply.
    """
    comparisons = tuple(_RECOLLECTION_COMPARISON.finditer(text))
    if len(comparisons) != 1:
        return text
    comparison = comparisons[0]
    before, recalled = text[: comparison.start()], text[comparison.start() :]
    in_before = disaster in disasters_in_text(before)
    in_recalled = disaster in disasters_in_text(recalled)
    if in_recalled and not in_before:
        return recalled
    if in_before and not in_recalled:
        return before.rstrip(" ,")
    return text


def has_competing_cause(text: str) -> bool:
    drought_links = tuple(_DROUGHT_FAMINE_LINK.finditer(text))
    unrelated_famine = any(
        # A link must govern this dated famine, not a different famine elsewhere.
        not any(
            link.start() <= famine.start() and famine.end() <= link.end()
            for link in drought_links
        )
        for famine in _DATED_FAMINE.finditer(text)
    )
    precursor_accident = any(
        # An earlier supported hazard could itself have caused the accident.
        # Preserve that attributed account rather than assume the new fire did.
        not disasters_in_text(text[: match.start("fire")])
        for match in _FATAL_FIRE_IGNITION_ACCIDENT.finditer(text)
    )
    return (
        bool(_OTHER_CAUSE.search(text))
        or unrelated_famine
        or regional_competing_cause(text)
        or precursor_accident
    )


def scoped_disaster_text(text: str, title: str, disaster: Disaster | None) -> str:
    """Never assign competing causes or another hazard's figures to this event.

    An unambiguous hazard headline can supply context for otherwise unqualified
    sentences. Broad/multi-topic headlines require the hazard in the same sentence.
    Mixed-cause sentences remain in the source, rather than becoming hazard totals.
    """
    if disaster is None:
        return ""
    headline_context = disasters_in_text(title) == (disaster,)
    retained = []
    for sentence in source_sentences(text[:20_000]):
        sentence = _recollection_account(sentence, disaster)
        if has_competing_cause(sentence):
            continue
        hazards = disasters_in_text(sentence)
        if not hazards and has_regional_weather_toll(sentence):
            # A local hazard headline does not allocate wider rain/storm deaths.
            # The complete original account remains in the retained article.
            continue
        if hazards == (disaster,) or (not hazards and headline_context):
            retained.append(sentence)
    return " ".join(retained)
