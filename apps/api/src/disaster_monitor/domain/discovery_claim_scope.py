"""Bound attributed disaster accounts inside potentially multi-topic reporting.

These are bounded literal language rules, not semantic causal verification. Original
report text and links remain retained even when an account cannot be safely scoped.
"""

import re
from dataclasses import dataclass

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery_accident_accounts import scoped_accident_account
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.regional_accounts import (
    has_french_fatal_mass_wording,
    has_regional_weather_toll,
    regional_competing_cause,
)
from disaster_monitor.domain.reported_number_wording import REPORTED_NUMBER
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


# Explicit competing-weather accounts are different from a trigger of the hazard.
_LIGHTNING_FATALITY = re.compile(
    r"\blightning(?:[-\s]+strikes?)?\s+(?:kill(?:ed|s|ing)|claim(?:ed|s|ing))\b|"
    r"\blightning[-\s]+(?:related[-\s]+)?(?:deaths?|fatalities)\b|"
    r"\b(?:killed|died|dead|deaths?)\b[^.!?;,]{0,45}"
    r"\b(?:by|from|due to)\s+(?:a\s+|the\s+)?lightning\b",
    re.I,
)
_WEATHER_ACCOUNT = re.compile(
    r"\b(?:rain|weather|storm)[-\s]+related\s+"
    r"(?:incidents?|accidents?|deaths?|fatalities)\b",
    re.I,
)
_FATAL_WORD = re.compile(r"\b(?:killed|died|dead|deaths?|fatalities)\b", re.I)
_CASUALTY_PREDICATE = re.compile(
    r"\b(?:kill(?:ed|s|ing)|died|claim(?:ed|s|ing))\b", re.I
)
_WEATHER_CLAUSES = re.compile(r",\s+|\b(?:and|while|whereas|but|with|as)\b", re.I)
_JOINT_WEATHER_SUBJECT = re.compile(
    r"\blightning(?:\s+strikes?)?\s+(?:and|or)\s+(?P<right>[^.!?;,]{1,70}?)"
    r"\s+(?:killed|kills|claimed|claims|left)\b|"
    r"(?P<left>[^.!?;,]{1,70}?)\s+(?:and|or)\s+lightning(?:\s+strikes?)?"
    r"\s+(?:killed|kills|claimed|claims|left)\b",
    re.I,
)
_HAZARD_TRIGGER = re.compile(
    r"\b(?:caused|triggered|sparked|ignited|started|generated|led|brought|fanned)\b",
    re.I,
)
_FATALITY_SUBSET = re.compile(
    rf"\bincluding\s+(?P<count>{REPORTED_NUMBER})\s+"
    r"(?:(?:people|persons?|victims?|workers?)\s+)?"
    r"(?:in|from|due to)\s+(?P<cause>[^.!?;,]{1,100})",
    re.I,
)
_LISTED_FATALITIES = re.compile(r"\b(?:reported\s+)?(?:fatalities|deaths)\s*,", re.I)


@dataclass(frozen=True, slots=True)
class HazardFatalitySubset:
    disaster: Disaster
    value: str


def explicit_hazard_fatality_subset(text: str) -> HazardFatalitySubset | None:
    """An explicit local subset is not the preceding whole weather account."""
    matches = tuple(_FATALITY_SUBSET.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    if not _FATAL_WORD.search(text[: match.start()]):
        return None
    causes = disasters_in_text(match["cause"])
    if len(causes) != 1 or disasters_in_text(text) != causes:
        return None
    return HazardFatalitySubset(causes[0], match["count"].replace(",", ""))


def _joint_weather_toll(text: str, disaster: Disaster) -> bool:
    for match in _JOINT_WEATHER_SUBJECT.finditer(text):
        subject = match["left"] or match["right"]
        if (
            disaster in disasters_in_text(subject)
            and not _CASUALTY_PREDICATE.search(subject)
            and not _HAZARD_TRIGGER.search(subject)
        ):
            return True
    return False


def _weather_account_scope(
    text: str, disaster: Disaster, *, mixed_context: bool
) -> str:
    subset = explicit_hazard_fatality_subset(text)
    if subset is not None and subset.disaster is disaster:
        return text
    if _joint_weather_toll(text, disaster):
        return ""
    explicit_other = bool(_LIGHTNING_FATALITY.search(text)) or bool(
        _WEATHER_ACCOUNT.search(text) and _FATAL_WORD.search(text)
    )
    if not explicit_other:
        if mixed_context and (
            _LISTED_FATALITIES.search(text) and not _CASUALTY_PREDICATE.search(text)
        ):
            return ""
        return text
    retained = []
    for clause in _WEATHER_CLAUSES.split(text):
        if disaster not in disasters_in_text(clause) or _LIGHTNING_FATALITY.search(
            clause
        ):
            continue
        weather = _WEATHER_ACCOUNT.search(clause)
        if weather:
            fatal = _FATAL_WORD.search(clause)
            if (
                fatal is None
                or weather.start() < fatal.start()
                or disaster not in disasters_in_text(clause[: fatal.start()])
            ):
                continue
        retained.append(clause.strip(" ,;").rstrip("."))
    return ". ".join(retained)


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


_FRENCH_CLAUSE_BOUNDARY = re.compile(
    r",\s*(?:et|mais|tandis que|alors que)\s+",
    re.I,
)


def separate_regional_hazard_accounts(text: str) -> list[str]:
    """Split explicit French predicates, never a coordinated shared subject/toll."""
    if not has_french_fatal_mass_wording(text):
        return [text]
    clauses = _FRENCH_CLAUSE_BOUNDARY.split(text)
    hazards = [disasters_in_text(clause) for clause in clauses]
    predicates = all(
        re.search(
            r"\b(?:a|ont|avait|avaient)\s+"
            r"(?:fait|tu[eé]|caus[eé]|touch[eé]|endommag[eé]|d[eé]truit|"
            r"enseveli|frapp[eé]|provoqu[eé]|[eé]t[eé])\b|"
            r"\b(?:est|sont)\s+(?:survenu(?:e|s|es)?|signal[eé](?:e|s|es)?)\b|"
            r"\b(?:font|fait|tue(?:nt)?|touche(?:nt)?)\b",
            clause,
            re.I,
        )
        for clause in clauses
    )
    if (
        len(clauses) > 1
        and predicates
        and all(len(value) == 1 for value in hazards)
        and len({value[0] for value in hazards}) > 1
    ):
        return clauses
    return [text]


def scoped_disaster_text(
    text: str,
    title: str,
    disaster: Disaster | None,
    *,
    source_context: str | None = None,
) -> str:
    """Never assign competing causes or another hazard's figures to this event.

    An unambiguous hazard headline can supply context for otherwise unqualified
    sentences. Broad/multi-topic headlines require the hazard in the same sentence.
    Mixed-cause sentences remain in the source, rather than becoming hazard totals.
    """
    if disaster is None:
        return ""
    headline_context = disasters_in_text(title) == (disaster,)
    context = (text if source_context is None else source_context)[:20_000]
    mixed_weather_context = bool(_LIGHTNING_FATALITY.search(context)) or bool(
        _WEATHER_ACCOUNT.search(context) and _FATAL_WORD.search(context)
    )
    retained = []
    for sentence in source_sentences(text[:20_000]):
        sentence = scoped_accident_account(sentence, disaster)
        if not sentence:
            continue
        sentence = _recollection_account(sentence, disaster)
        if has_competing_cause(sentence):
            continue
        sentence = _weather_account_scope(
            sentence, disaster, mixed_context=mixed_weather_context
        )
        for clause in separate_regional_hazard_accounts(sentence):
            hazards = disasters_in_text(clause)
            if not hazards and has_regional_weather_toll(clause):
                # A local headline does not allocate a wider rain/storm toll.
                continue
            if hazards == (disaster,) or (not hazards and headline_context):
                retained.append(clause)
    return " ".join(retained)
