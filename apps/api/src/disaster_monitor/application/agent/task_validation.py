"""Deterministic validation of classified disaster tasks."""

import re
from dataclasses import replace

from disaster_monitor.application.agent.canonical_task_validation import (
    _limited_task,
    _validate_canonical_task,
)
from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    InformationNeed,
    InvestigationTarget,
    OutputModality,
    TaskKind,
    ValidatedDisasterTask,
    ValidationStatus,
)
from disaster_monitor.application.agent.operator_actions import (
    validate_operator_action_candidates,
)
from disaster_monitor.application.agent.task_classification import (
    _PLACE_AFTER_IN,
    _WORLDWIDE_MARKERS,
    _disaster_mentions,
    _information_needs,
    _output_modalities,
    disaster_safety_gate,
    worldwide_disaster_query,
)
from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    QueryParseStatus,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
    has_explicit_date,
)
from disaster_monitor.application.services.disaster_query_policy import (
    default_disaster_query_policies,
)


def validate_disaster_task(
    question: str,
    draft: DisasterTaskDraft,
    *,
    country_catalog: CountryCatalog,
    query_parser: DisasterQueryParser,
) -> ValidatedDisasterTask:
    """Canonicalize only through maintained deterministic application metadata."""
    task = _validate_two_hazard_task(
        question,
        draft,
        country_catalog=country_catalog,
    )
    if task is None:
        task = _validate_disaster_task(
            question,
            draft,
            country_catalog=country_catalog,
            query_parser=query_parser,
        )
    return replace(
        task,
        operator_action_ids=validate_operator_action_candidates(
            draft.operator_action_ids
        ),
    )


def _validate_two_hazard_task(
    question: str,
    draft: DisasterTaskDraft,
    *,
    country_catalog: CountryCatalog,
) -> ValidatedDisasterTask | None:
    """Admit only deterministic, current, country-scoped two-hazard requests.

    This runs before canonical model validation so the model cannot select one of the
    hazards or provide the identity of a second branch.
    """
    disasters = _disaster_mentions(question)
    if len(disasters) < 2 or not disaster_safety_gate(question):
        return None
    needs = _information_needs(question)
    modalities = _output_modalities(question) or (OutputModality.TEXT,)
    response_language = _safe_response_language(draft.requested_response_language)
    if len(disasters) != 2:
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            "Investigation Agent v1 supports exactly two explicit disasters in one "
            "country-scoped investigation.",
            information_needs=needs,
            output_modalities=modalities,
            response_language=response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    if _WORLDWIDE_MARKERS.search(question):
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            "Investigation Agent v1 supports exactly one maintained country, not "
            "worldwide two-hazard coverage.",
            information_needs=needs,
            output_modalities=modalities,
            response_language=response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    if has_explicit_date(question):
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            "Explicit historical calendar and date-range two-hazard investigations "
            "are not supported in Investigation Agent v1.",
            information_needs=needs,
            output_modalities=modalities,
            response_language=response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    countries = country_catalog.find_mentions(question)
    if len(countries) > 1:
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            "Investigation Agent v1 can investigate exactly one country at a time. "
            "Which country should I use?",
            information_needs=needs,
            output_modalities=modalities,
            response_language=response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    if not countries:
        unresolved = next(iter(draft.place_mentions), None) or next(
            (match.group(1).strip() for match in _PLACE_AFTER_IN.finditer(question)),
            None,
        )
        return _limited_task(
            question,
            True,
            ValidationStatus.CATALOG_LIMITATION,
            f"{unresolved or 'The requested place'} is not in the maintained "
            "geographic and source catalog. I cannot create trusted country metadata.",
            unresolved_place=unresolved,
            information_needs=needs,
            output_modalities=modalities,
            response_language=response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    country = countries[0]
    targets = tuple(
        InvestigationTarget(
            target_id=(
                f"investigation-target:v1:{country.alpha3_code}:{index}:"
                f"{disaster.value}"
            ),
            disaster=disaster,
            country=country,
            query=DisasterQuery(
                disaster=disaster,
                country=country,
                time_intent="recent",
                focus=tuple(item.value for item in needs),
                event_discriminators=default_disaster_query_policies()
                .for_disaster(disaster)
                .discriminators(question),
            ),
            information_needs=needs,
            output_modalities=modalities,
        )
        for index, disaster in enumerate(disasters, start=1)
    )
    return ValidatedDisasterTask(
        question=question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        country=country,
        information_needs=needs,
        output_modalities=modalities,
        response_language=response_language,
        response_language_explicit=draft.response_language_explicit,
        investigation_targets=targets,
    )


def _safe_response_language(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z]{2,12}(?:[-_][A-Za-z0-9]{2,12})?", value
    ):
        return None
    return value


def _validate_disaster_task(
    question: str,
    draft: DisasterTaskDraft,
    *,
    country_catalog: CountryCatalog,
    query_parser: DisasterQueryParser,
) -> ValidatedDisasterTask:
    """Build a canonical task before attaching safe operator candidates."""
    if draft.canonical:
        return _validate_canonical_task(
            question,
            draft,
            country_catalog=country_catalog,
            query_parser=query_parser,
        )
    safety_requires_evidence = disaster_safety_gate(question)
    deterministic_disasters = _disaster_mentions(question)
    if not deterministic_disasters:
        return ValidatedDisasterTask(
            question, TaskKind.NON_DISASTER, False, information_needs=()
        )
    disasters = deterministic_disasters
    requires_evidence = safety_requires_evidence
    if not requires_evidence:
        return ValidatedDisasterTask(
            question,
            TaskKind.GENERAL_KNOWLEDGE,
            False,
            disaster=disasters[0] if len(disasters) == 1 else None,
            information_needs=(InformationNeed.GENERAL_INFORMATION,),
        )
    if len(disasters) != 1:
        detail = (
            "Please specify exactly one disaster disaster for this investigation."
            if len(disasters) > 1
            else "Please specify the disaster disaster to investigate."
        )
        return _limited_task(
            question,
            requires_evidence,
            ValidationStatus.CLARIFICATION_REQUIRED,
            detail,
        )

    worldwide_query = worldwide_disaster_query(question)
    if worldwide_query is not None:
        return ValidatedDisasterTask(
            question=question,
            kind=TaskKind.INVESTIGATION,
            requires_evidence=True,
            disaster=disasters[0],
            geographic_scope=GeographicScope.WORLDWIDE,
            information_needs=_information_needs(question),
            output_modalities=_output_modalities(question) or (OutputModality.TEXT,),
            worldwide_query=worldwide_query,
        )

    countries = country_catalog.find_mentions(question)
    if len(countries) > 1:
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            "This phase can investigate exactly one country at a time. "
            "Which country should I use?",
            disaster=disasters[0],
        )
    if not countries:
        unresolved = next(iter(draft.place_mentions), None) or next(
            (match.group(1).strip() for match in _PLACE_AFTER_IN.finditer(question)),
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
            disaster=disasters[0],
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
            disaster=disasters[0],
        )
    if parsed.query is None:
        return _limited_task(
            question,
            True,
            ValidationStatus.CLARIFICATION_REQUIRED,
            parsed.detail or "The disaster request could not be normalized safely.",
            disaster=disasters[0],
        )
    needs = _information_needs(question)
    modalities = _output_modalities(question)
    return ValidatedDisasterTask(
        question=question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        disaster=disasters[0],
        country=countries[0],
        date_from=parsed.query.date_from,
        date_to=parsed.query.date_to,
        event_discriminators=(),
        information_needs=needs or (InformationNeed.EVENT_OVERVIEW,),
        output_modalities=modalities or (OutputModality.TEXT,),
        query=parsed.query,
    )
