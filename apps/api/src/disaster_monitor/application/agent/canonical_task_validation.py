"""Validation and bounded repair of canonical model-produced tasks."""

import re
from datetime import UTC, datetime

from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    InformationNeed,
    OutputModality,
    TaskKind,
    ValidatedDisasterTask,
    ValidationStatus,
)
from disaster_monitor.application.agent.task_classification import (
    _CURRENT_EVENT_MARKERS,
    _information_needs,
    _output_modalities,
)
from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    WorldwideDisasterQuery,
    WorldwideSelectionIntent,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
    has_explicit_date,
)
from disaster_monitor.application.services.disaster_query_policy import (
    default_disaster_query_policies,
)
from disaster_monitor.domain.disaster import Country, Disaster


def _validate_canonical_task(
    question: str,
    draft: DisasterTaskDraft,
    *,
    country_catalog: CountryCatalog,
    query_parser: DisasterQueryParser,
) -> ValidatedDisasterTask:
    """Validate model semantics, repairing only incomplete trusted date metadata."""
    if draft.requested_response_language is not None and (
        not isinstance(draft.requested_response_language, str)
        or not re.fullmatch(
            r"[A-Za-z]{2,12}(?:[-_][A-Za-z0-9]{2,12})?",
            draft.requested_response_language,
        )
    ):
        return _canonical_invalid(
            question, "The model returned an invalid response language tag."
        )
    if not isinstance(draft.task_kind, TaskKind):
        return _canonical_invalid(
            question, "The model returned an unsupported task kind."
        )
    if draft.task_kind is TaskKind.NON_DISASTER:
        return ValidatedDisasterTask(
            question,
            TaskKind.NON_DISASTER,
            False,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )

    if not isinstance(draft.disaster, Disaster):
        return _canonical_invalid(
            question,
            "The model did not return one supported disaster enum value.",
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )

    needs, modalities, detail = _canonical_needs_and_modalities(draft)
    if detail is not None:
        return _canonical_invalid(
            question,
            detail,
            disaster=draft.disaster,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )

    if draft.task_kind is TaskKind.GENERAL_KNOWLEDGE:
        return ValidatedDisasterTask(
            question=question,
            kind=TaskKind.GENERAL_KNOWLEDGE,
            requires_evidence=False,
            disaster=draft.disaster,
            information_needs=(InformationNeed.GENERAL_INFORMATION,),
            output_modalities=modalities,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )

    if not draft.current_or_event_specific:
        return _canonical_invalid(
            question,
            draft.clarification_question
            or "The model did not establish a current or event-specific request.",
            disaster=draft.disaster,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    scope = draft.geographic_scope or GeographicScope.COUNTRY
    discriminator_requested = bool(draft.event_discriminators) or bool(
        default_disaster_query_policies()
        .for_disaster(draft.disaster)
        .discriminators(question)
    )
    if scope is GeographicScope.WORLDWIDE and discriminator_requested:
        return _canonical_invalid(
            question,
            "The model proposed an unsupported event discriminator.",
            disaster=draft.disaster,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    explicit_date_requested = has_explicit_date(question)
    recent_window_requested = (
        bool(_CURRENT_EVENT_MARKERS.search(question)) and not explicit_date_requested
    )
    incomplete_date_range = not recent_window_requested and (
        draft.date_from is None
    ) != (draft.date_to is None)
    deterministic_date_requested = (
        scope is GeographicScope.COUNTRY and explicit_date_requested
    )
    dates, date_detail = (
        ((None, None), None) if recent_window_requested else _canonical_dates(draft)
    )
    matched_query = None
    if incomplete_date_range or deterministic_date_requested or discriminator_requested:
        matched_query = _matching_deterministic_query(
            question,
            draft,
            country_catalog=country_catalog,
            query_parser=query_parser,
        )
    if (
        incomplete_date_range or deterministic_date_requested
    ) and matched_query is not None:
        if matched_query.date_from is not None and matched_query.date_to is not None:
            dates = matched_query.date_from, matched_query.date_to
            date_detail = None
    if date_detail is not None:
        return _canonical_invalid(
            question,
            date_detail,
            disaster=draft.disaster,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    if deterministic_date_requested and matched_query is None:
        return _canonical_invalid(
            question,
            "The explicit event date could not be normalized safely.",
            disaster=draft.disaster,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    if discriminator_requested and (
        matched_query is None or not matched_query.event_discriminators
    ):
        return _canonical_invalid(
            question,
            "The explicit event discriminator could not be normalized safely.",
            disaster=draft.disaster,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    date_from, date_to = dates
    if scope is GeographicScope.WORLDWIDE:
        if (
            draft.country_code
            or draft.country_name
            or draft.place_mentions
            or date_from is not None
        ):
            return _canonical_invalid(
                question,
                "The model returned conflicting country and worldwide geography "
                "metadata; no trusted scope was created.",
                disaster=draft.disaster,
                response_language=draft.requested_response_language,
                response_language_explicit=draft.response_language_explicit,
            )
        selection = draft.worldwide_selection or WorldwideSelectionIntent.LATEST.value
        try:
            selection_intent = WorldwideSelectionIntent(selection)
        except ValueError:
            return _canonical_invalid(
                question,
                "The model returned an unsupported worldwide selection.",
                disaster=draft.disaster,
            )
        return ValidatedDisasterTask(
            question=question,
            kind=TaskKind.INVESTIGATION,
            requires_evidence=True,
            disaster=draft.disaster,
            geographic_scope=scope,
            information_needs=needs,
            output_modalities=modalities,
            worldwide_query=WorldwideDisasterQuery(
                disaster=draft.disaster,
                selection_intent=selection_intent,
            ),
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    if scope is not GeographicScope.COUNTRY:
        return _canonical_invalid(
            question,
            "The model returned an unsupported geographic scope.",
            disaster=draft.disaster,
        )

    country = _resolve_canonical_country(draft, country_catalog)
    if country is None:
        unresolved = draft.country_name or draft.country_code
        return _limited_task(
            question,
            True,
            ValidationStatus.CATALOG_LIMITATION,
            f"{unresolved or 'The requested place'} is not in the maintained "
            "geographic and source catalog. I cannot create trusted country metadata.",
            disaster=draft.disaster,
            unresolved_place=unresolved,
            information_needs=needs,
            output_modalities=modalities,
            response_language=draft.requested_response_language,
            response_language_explicit=draft.response_language_explicit,
        )
    query = DisasterQuery(
        disaster=draft.disaster,
        country=country,
        time_intent="specified" if date_from is not None else "recent",
        focus=tuple(item.value for item in needs),
        date_from=date_from,
        date_to=date_to,
        event_discriminators=(
            matched_query.event_discriminators if matched_query is not None else ()
        ),
    )
    return ValidatedDisasterTask(
        question=question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        disaster=draft.disaster,
        country=country,
        date_from=date_from,
        date_to=date_to,
        information_needs=needs,
        output_modalities=modalities,
        query=query,
        response_language=draft.requested_response_language,
        response_language_explicit=draft.response_language_explicit,
    )


def _canonical_needs_and_modalities(
    draft: DisasterTaskDraft,
) -> tuple[tuple[InformationNeed, ...], tuple[OutputModality, ...], str | None]:
    try:
        needs = tuple(InformationNeed(value) for value in draft.information_needs)
        modalities = tuple(OutputModality(value) for value in draft.output_modalities)
    except (TypeError, ValueError):
        return (
            (),
            (),
            "The model returned an unsupported information need or output modality.",
        )
    if not needs:
        needs = (InformationNeed.EVENT_OVERVIEW,)
    if not modalities:
        modalities = (OutputModality.TEXT,)
    return needs, modalities, None


def _canonical_dates(
    draft: DisasterTaskDraft,
) -> tuple[tuple[datetime | None, datetime | None], str | None]:
    if (draft.date_from is None) != (draft.date_to is None):
        return (None, None), "Canonical date ranges require both date_from and date_to."
    if draft.date_from is None:
        return (None, None), None
    try:
        date_from = _canonical_datetime(draft.date_from)
        date_to = _canonical_datetime(draft.date_to or "")
    except (AttributeError, TypeError, ValueError):
        return (None, None), "The model returned an invalid canonical date range."
    if date_from >= date_to:
        return (None, None), "The model returned a reversed canonical date range."
    return (date_from, date_to), None


def _matching_deterministic_query(
    question: str,
    draft: DisasterTaskDraft,
    *,
    country_catalog: CountryCatalog,
    query_parser: DisasterQueryParser,
) -> DisasterQuery | None:
    country = _resolve_canonical_country(draft, country_catalog)
    parsed = query_parser.parse(question)
    query = parsed.query
    if (
        country is None
        or query is None
        or query.disaster is not draft.disaster
        or query.country.alpha3_code != country.alpha3_code
    ):
        return None
    return query


def _canonical_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Canonical timestamps require an explicit timezone.")
    return parsed.astimezone(UTC)


def _resolve_canonical_country(
    draft: DisasterTaskDraft,
    country_catalog: CountryCatalog,
) -> Country | None:
    if draft.country_code is not None and not isinstance(draft.country_code, str):
        return None
    if draft.country_name is not None and not isinstance(draft.country_name, str):
        return None
    country = (
        country_catalog.get_by_alpha3(draft.country_code)
        if draft.country_code
        else None
    )
    if country is None and draft.country_name:
        matches = country_catalog.find_mentions(draft.country_name)
        if len(matches) == 1:
            country = matches[0]
    if country is None:
        return None
    if (
        draft.country_name
        and draft.country_name.casefold() != country.canonical_name.casefold()
    ):
        return None
    if draft.country_code and country.alpha3_code != draft.country_code.upper():
        return None
    return country


def _canonical_invalid(
    question: str,
    detail: str,
    *,
    disaster: Disaster | None = None,
    response_language: str | None = None,
    response_language_explicit: bool = False,
) -> ValidatedDisasterTask:
    return ValidatedDisasterTask(
        question=question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        disaster=disaster,
        validation_status=ValidationStatus.CLARIFICATION_REQUIRED,
        detail=detail,
        response_language=response_language,
        response_language_explicit=response_language_explicit,
    )


def _limited_task(
    question: str,
    requires_evidence: bool,
    status: ValidationStatus,
    detail: str,
    *,
    disaster: Disaster | None = None,
    unresolved_place: str | None = None,
    information_needs: tuple[InformationNeed, ...] | None = None,
    output_modalities: tuple[OutputModality, ...] | None = None,
    response_language: str | None = None,
    response_language_explicit: bool = False,
) -> ValidatedDisasterTask:
    return ValidatedDisasterTask(
        question=question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=requires_evidence,
        disaster=disaster,
        unresolved_place=unresolved_place,
        validation_status=status,
        detail=detail,
        information_needs=information_needs or _information_needs(question),
        output_modalities=output_modalities
        or _output_modalities(question)
        or (OutputModality.TEXT,),
        response_language=response_language,
        response_language_explicit=response_language_explicit,
    )
