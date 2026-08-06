"""Deterministic safety gating and canonical disaster-task validation."""

import re
from collections.abc import Callable

from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    InformationNeed,
    OutputModality,
    TaskKind,
    ValidatedDisasterTask,
    ValidationStatus,
)
from disaster_monitor.application.disaster import QueryParseStatus
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import Hazard

_HAZARDS: dict[Hazard, tuple[str, ...]] = {
    Hazard.EARTHQUAKE: ("earthquake", "earthquakes", "quake", "quakes"),
    Hazard.TSUNAMI: ("tsunami", "tsunamis"),
    Hazard.FLOOD: ("flood", "floods", "flooding"),
    Hazard.WILDFIRE: ("wildfire", "wildfires", "forest fire"),
    Hazard.LANDSLIDE: ("landslide", "landslides"),
    Hazard.TROPICAL_CYCLONE: ("typhoon", "hurricane", "cyclone"),
}
_EVIDENCE_MARKERS = re.compile(
    r"\b(?:latest|recent|current|today|now|reported|caused|fatalit(?:y|ies)|"
    r"killed|dead|injur(?:y|ies|ed)|missing|evacuat\w*|damage\w*|warning\w*|"
    r"response|pictures?|images?|photos?|timeline|map layers?|on\s+(?:january|"
    r"february|march|april|may|june|july|august|september|october|november|"
    r"december)|20\d{2}-\d{2}-\d{2})\b",
    re.I,
)
_PLACE_AFTER_IN = re.compile(
    r"\b(?:in|from|across)\s+([A-Z][A-Za-z .'-]{1,60}?)(?=[?.!,]|\s+(?:on|and)\b|$)"
)
_KNOWN_UNCATALOGED_COUNTRIES = ("Thailand",)


def disaster_safety_gate(question: str) -> bool:
    """Conservatively retain factual disaster requests in the trusted path."""
    hazards = _hazard_mentions(question)
    return bool(hazards and _EVIDENCE_MARKERS.search(question))


def deterministic_task_draft(question: str) -> DisasterTaskDraft:
    hazards = tuple(hazard.value for hazard in _hazard_mentions(question))
    places = list(_extract_raw_places(question))
    needs = tuple(item.value for item in _information_needs(question))
    modalities = tuple(item.value for item in _output_modalities(question))
    evidence = disaster_safety_gate(question)
    return DisasterTaskDraft(
        disaster_related=bool(hazards),
        current_or_event_specific=evidence,
        hazard_mentions=hazards,
        place_mentions=tuple(places),
        information_needs=needs,
        output_modalities=modalities,
    )


def validate_disaster_task(
    question: str,
    draft: DisasterTaskDraft,
    *,
    country_catalog: CountryCatalog,
    query_parser: DisasterQueryParser,
) -> ValidatedDisasterTask:
    """Canonicalize only through maintained deterministic application metadata."""
    safety_requires_evidence = disaster_safety_gate(question)
    deterministic_hazards = _hazard_mentions(question)
    draft_hazards = tuple(_canonical_hazard(value) for value in draft.hazard_mentions)
    hazards = tuple(
        dict.fromkeys(
            hazard
            for hazard in (*deterministic_hazards, *draft_hazards)
            if hazard is not None
        )
    )
    disaster_related = bool(deterministic_hazards) or draft.disaster_related
    requires_evidence = safety_requires_evidence or draft.current_or_event_specific
    if not disaster_related:
        return ValidatedDisasterTask(
            question, TaskKind.NON_DISASTER, False, information_needs=()
        )
    if not requires_evidence:
        return ValidatedDisasterTask(
            question,
            TaskKind.GENERAL_KNOWLEDGE,
            False,
            hazard=hazards[0] if len(hazards) == 1 else None,
            information_needs=(InformationNeed.GENERAL_INFORMATION,),
        )
    if len(hazards) != 1:
        detail = (
            "Please specify exactly one disaster hazard for this investigation."
            if len(hazards) > 1
            else "Please specify the disaster hazard to investigate."
        )
        return _limited_task(
            question,
            requires_evidence,
            ValidationStatus.CLARIFICATION_REQUIRED,
            detail,
        )

    countries = country_catalog.find_mentions(question)
    draft_countries = tuple(
        country
        for mention in draft.place_mentions
        for country in country_catalog.find_mentions(mention)
    )
    countries = tuple(
        {
            country.alpha3_code: country for country in (*countries, *draft_countries)
        }.values()
    )
    if len(countries) > 1:
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            "This phase can investigate exactly one country at a time. "
            "Which country should I use?",
            hazard=hazards[0],
        )
    if not countries:
        unresolved = next(iter(draft.place_mentions), None) or next(
            (
                name
                for name in _KNOWN_UNCATALOGED_COUNTRIES
                if name.lower() in question.lower()
            ),
            None,
        )
        detail = (
            f"{unresolved or 'The requested place'} is not in the maintained "
            "geographic and source catalog. I cannot create trusted country metadata."
        )
        return _limited_task(
            question,
            True,
            ValidationStatus.CATALOG_LIMITATION,
            detail,
            hazard=hazards[0],
            unresolved_place=unresolved,
        )

    parsed = query_parser.parse(question)
    if parsed.status == QueryParseStatus.MULTIPLE_COUNTRIES:
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            "This phase can investigate exactly one country at a time. "
            "Which country should I use?",
            hazard=hazards[0],
        )
    if parsed.query is None:
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            parsed.detail or "The disaster request could not be normalized safely.",
            hazard=hazards[0],
        )
    needs = _merge_enum_values(
        _information_needs(question), draft.information_needs, InformationNeed
    )
    modalities = _merge_enum_values(
        _output_modalities(question), draft.output_modalities, OutputModality
    )
    return ValidatedDisasterTask(
        question=question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        hazard=hazards[0],
        country=countries[0],
        date_from=parsed.query.date_from,
        date_to=parsed.query.date_to,
        event_discriminators=draft.event_discriminators,
        information_needs=needs or (InformationNeed.EVENT_OVERVIEW,),
        output_modalities=modalities or (OutputModality.TEXT,),
        query=parsed.query,
    )


def _limited_task(
    question: str,
    requires_evidence: bool,
    status: ValidationStatus,
    detail: str,
    *,
    hazard: Hazard | None = None,
    unresolved_place: str | None = None,
) -> ValidatedDisasterTask:
    return ValidatedDisasterTask(
        question=question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=requires_evidence,
        hazard=hazard,
        unresolved_place=unresolved_place,
        validation_status=status,
        detail=detail,
        information_needs=_information_needs(question),
        output_modalities=_output_modalities(question) or (OutputModality.TEXT,),
    )


def _canonical_hazard(value: str) -> Hazard | None:
    normalized = value.strip().lower().replace(" ", "_")
    for hazard, aliases in _HAZARDS.items():
        if normalized == hazard.value or normalized.replace("_", " ") in aliases:
            return hazard
    return None


def _hazard_mentions(text: str) -> tuple[Hazard, ...]:
    return tuple(
        hazard
        for hazard, aliases in _HAZARDS.items()
        if any(
            re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, re.I)
            for alias in aliases
        )
    )


def _information_needs(text: str) -> tuple[InformationNeed, ...]:
    patterns = (
        (InformationNeed.FATALITIES, r"\b(?:fatalit(?:y|ies)|killed|dead)\b"),
        (InformationNeed.INJURIES, r"\binjur(?:y|ies|ed)\b"),
        (InformationNeed.MISSING_PERSONS, r"\bmissing\b"),
        (InformationNeed.EVACUATIONS, r"\bevacuat\w*\b"),
        (InformationNeed.PHYSICAL_DAMAGE, r"\bdamage\w*\b"),
        (
            InformationNeed.INFRASTRUCTURE_DISRUPTION,
            r"\b(?:infrastructure|outage|road|bridge)\w*\b",
        ),
        (InformationNeed.WARNINGS, r"\bwarning\w*\b"),
        (InformationNeed.EMERGENCY_RESPONSE, r"\b(?:emergency|government|response)\b"),
        (InformationNeed.IMAGES, r"\b(?:pictures?|images?|photos?)\b"),
        (InformationNeed.MAP_VISUALIZATION, r"\b(?:map|layers?)\b"),
        (InformationNeed.TIMELINE, r"\btimeline\b"),
    )
    found = tuple(need for need, pattern in patterns if re.search(pattern, text, re.I))
    return found or (InformationNeed.EVENT_OVERVIEW,)


def _output_modalities(text: str) -> tuple[OutputModality, ...]:
    modalities = [OutputModality.TEXT]
    if re.search(r"\b(?:how many|fatalit(?:y|ies)|killed|dead)\b", text, re.I):
        modalities.append(OutputModality.FOCUSED_FACT)
    if re.search(r"\btable\b", text, re.I):
        modalities.append(OutputModality.TABLE)
    if re.search(r"\b(?:pictures?|images?|photos?)\b", text, re.I):
        modalities.append(OutputModality.IMAGES)
    if re.search(r"\b(?:map|layers?)\b", text, re.I):
        modalities.append(OutputModality.MAP)
    if re.search(r"\btimeline\b", text, re.I):
        modalities.append(OutputModality.TIMELINE)
    return tuple(dict.fromkeys(modalities))


def _extract_raw_places(text: str) -> tuple[str, ...]:
    found = [match.group(1).strip() for match in _PLACE_AFTER_IN.finditer(text)]
    for country in _KNOWN_UNCATALOGED_COUNTRIES:
        if country.lower() in text.lower() and country not in found:
            found.append(country)
    return tuple(found[:4])


def _merge_enum_values[T](
    deterministic: tuple[T, ...],
    raw_values: tuple[str, ...],
    enum_type: Callable[[str], T],
) -> tuple[T, ...]:
    values = list(deterministic)
    for raw in raw_values[:12]:
        try:
            value = enum_type(raw)
        except ValueError:
            continue
        if value not in values:
            values.append(value)
    return tuple(values)
