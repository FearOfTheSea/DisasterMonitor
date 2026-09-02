"""Deterministic safety gating and canonical disaster-task validation."""

import re
from dataclasses import replace
from datetime import UTC, datetime

from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    InformationNeed,
    OutputModality,
    TaskKind,
    ValidatedDisasterTask,
    ValidationStatus,
)
from disaster_monitor.application.agent.operator_actions import (
    validate_operator_action_candidates,
)
from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    QueryParseStatus,
    WorldwideDisasterQuery,
    WorldwideSelectionIntent,
)
from disaster_monitor.application.disaster_aliases import recognized_disasters
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
    has_explicit_date,
)
from disaster_monitor.application.services.disaster_query_policy import (
    default_disaster_query_policies,
)
from disaster_monitor.application.services.worldwide_disaster_policy import (
    WorldwideDisasterPolicyRegistry,
    default_worldwide_disaster_policy_registry,
)
from disaster_monitor.domain.disaster import Country, Disaster

_CURRENT_EVENT_MARKERS = re.compile(
    r"(?:\b(?:latest|recent|current|today|now|news|ongoing|reported|confirmed|"
    r"this week|as of|struck|hit|occurred)\b|"
    r"\b(?:actual|reciente|hoy|ahora|reportad[oa]s?|confirmad[oa]s?)\b|"
    r"(?:mới nhất|gần đây|hiện tại|hôm nay|đã báo cáo|đã xác nhận|"
    r"最新|最近|現在|今日|報告|確認))",
    re.I,
)
_EVIDENCE_MARKERS = re.compile(
    r"(?:\b(?:fatalit(?:y|ies)|death toll|killed|dead|injur(?:y|ies|ed)|hurt|"
    r"wounded|missing|unaccounted|evacuat\w*|displaced|shelter\w*|damage\w*|"
    r"destroyed|collapsed|infrastructure|outage\w*|utilities|road\w*|bridge\w*|"
    r"warning\w*|alert\w*|advisory|watch|response|responders?|relief|rescue|aid|"
    r"pictures?|images?|photos?|imagery|timeline|chronology|map layers?)\b|"
    r"\b(?:decision support|options?|recommendations?|next steps?|what should)\b|"
    r"\b(?:muert(?:e|es|os)|fallecid[oa]s?|herid[oa]s?|desaparecid[oa]s?|"
    r"evacuad[oa]s?|desplazad[oa]s?|daños?|destruid[oa]s?|infraestructura|"
    r"cortes?|carreteras?|puentes?|alertas?|advertencias?|respuesta|rescate|"
    r"ayuda|fotos?|imágenes?|mapas?|cronología)\b|"
    r"\b(?:opciones?|recomendaciones?|próximos pasos|qué debería)\b|"
    r"(?:tử vong|người chết|bị thương|mất tích|sơ tán|di dời|thiệt hại|"
    r"phá hủy|cơ sở hạ tầng|mất điện|đường|cầu|cảnh báo|ứng phó|cứu hộ|"
    r"cứu trợ|hình ảnh|bản đồ|dòng thời gian|"
    r"phương án|khuyến nghị|bước tiếp theo|"
    r"死者|死亡|負傷|けが|行方不明|避難|被害|倒壊|インフラ|停電|道路|橋|"
    r"警報|注意報|対応|救助|支援|画像|写真|地図|時系列|"
    r"意思決定|選択肢|推奨|次のステップ))",
    re.I,
)
_GENERAL_KNOWLEDGE_MARKERS = re.compile(
    r"(?:\b(?:what causes|why (?:do|does)|how (?:do|does|are|is)|"
    r"what (?:is|are) (?:an? )?|define|definition|in general|hypothetical|"
    r"write (?:a )?(?:story|poem)|translate)\b|"
    r"\b(?:qué (?:es|son)|por qué|cómo (?:se|funciona)|en general|hipotétic[oa])\b|"
    r"(?:là gì|tại sao|hoạt động như thế nào|nói chung|"
    r"とは何|なぜ|仕組み|一般的))",
    re.I,
)
_PLACE_AFTER_IN = re.compile(
    r"\b(?:in|from|across)\s+([A-Z][A-Za-z .'-]{1,60}?)(?=[?.!,]|\s+(?:on|and)\b|$)"
)
_WORLDWIDE_MARKERS = re.compile(
    r"(?:\b(?:worldwide|globally|global|world|anywhere)\b|"
    r"\b(?:around|across|throughout)\s+the\s+world\b)",
    re.I,
)
_OBVIOUS_MAP_QUESTION = re.compile(
    r"\b(?:map|map\s+center|zoom|layers?|viewport)\b", re.I
)
_EXPLICIT_OPERATOR_UI_REQUEST = re.compile(
    r"(?:\b(?:open|launch|go\s+to)\s+(?:findings|sources?|source\s+catalog|"
    r"watches?|operations?)\b|"
    r"\b(?:show|display|enable|turn\s+on)\b[^?.!]{0,80}\b(?:layer|layers|"
    r"active\s+incidents?|satellite\s+imagery|cop\s+evidence)\b|"
    r"\b(?:monitor|watch|keep\s+an\s+eye\s+on)\b|"
    r"\b(?:1h|6h|24h|48h|7d)\b[^?.!]{0,40}\b(?:time|window|incidents?|map)\b)",
    re.I,
)


def is_obvious_non_disaster_map_question(question: str) -> bool:
    """Preserve the map-only fast path when no maintained disaster is present."""
    return (
        bool(_OBVIOUS_MAP_QUESTION.search(question))
        and not _disaster_mentions(question)
        and not _EXPLICIT_OPERATOR_UI_REQUEST.search(question)
    )


def worldwide_disaster_query(
    question: str,
    *,
    policies: WorldwideDisasterPolicyRegistry | None = None,
) -> WorldwideDisasterQuery | None:
    """Admit explicit current worldwide requests for any admitted disaster."""
    disasters = _disaster_mentions(question)
    if (
        len(disasters) != 1
        or not disaster_safety_gate(question)
        or not _WORLDWIDE_MARKERS.search(question)
    ):
        return None
    policy = (policies or default_worldwide_disaster_policy_registry()).for_disaster(
        disasters[0]
    )
    return WorldwideDisasterQuery(
        disaster=disasters[0], selection_intent=policy.selection_for(question)
    )


def disaster_safety_gate(question: str) -> bool:
    """Conservatively retain factual disaster requests in the trusted path."""
    disasters = _disaster_mentions(question)
    if not disasters:
        return False
    if _CURRENT_EVENT_MARKERS.search(question) or has_explicit_date(question):
        return True
    if _GENERAL_KNOWLEDGE_MARKERS.search(question):
        return False
    return bool(_EVIDENCE_MARKERS.search(question))


def deterministic_task_draft(question: str) -> DisasterTaskDraft:
    disasters = tuple(disaster.value for disaster in _disaster_mentions(question))
    places = list(_extract_raw_places(question))
    needs = tuple(item.value for item in _information_needs(question))
    modalities = tuple(item.value for item in _output_modalities(question))
    evidence = disaster_safety_gate(question)
    return DisasterTaskDraft(
        disaster_related=bool(disasters),
        current_or_event_specific=evidence,
        disaster_mentions=disasters,
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


def _disaster_mentions(text: str) -> tuple[Disaster, ...]:
    return recognized_disasters(text)


def _information_needs(text: str) -> tuple[InformationNeed, ...]:
    patterns = (
        (
            InformationNeed.FATALITIES,
            r"(?:\b(?:fatalit(?:y|ies)|death toll|killed|dead|lives lost)\b|"
            r"\b(?:muert(?:e|es|os)|fallecid[oa]s?)\b|"
            r"(?:tử vong|người chết|死者|死亡))",
        ),
        (
            InformationNeed.INJURIES,
            r"(?:\b(?:injur(?:y|ies|ed)|hurt|wounded)\b|"
            r"\b(?:herid[oa]s?|lesionad[oa]s?)\b|(?:bị thương|負傷|けが))",
        ),
        (
            InformationNeed.MISSING_PERSONS,
            r"(?:\b(?:missing|unaccounted for|unlocated)\b|"
            r"\bdesaparecid[oa]s?\b|(?:mất tích|行方不明))",
        ),
        (
            InformationNeed.EVACUATIONS,
            r"(?:\b(?:evacuat\w*|displaced|shelter(?:ed|ing)?)\b|"
            r"\b(?:evacuad[oa]s?|desplazad[oa]s?)\b|(?:sơ tán|di dời|避難))",
        ),
        (
            InformationNeed.PHYSICAL_DAMAGE,
            r"(?:\b(?:damage\w*|destroyed|collapsed|structural loss|homes? lost)\b|"
            r"\b(?:daños?|destruid[oa]s?|colapsad[oa]s?)\b|"
            r"(?:thiệt hại|phá hủy|sụp đổ|被害|倒壊))",
        ),
        (
            InformationNeed.INFRASTRUCTURE_DISRUPTION,
            r"(?:\b(?:infrastructure|outage\w*|utilities|power|water service|"
            r"telecom\w*|road\w*|bridge\w*|airport\w*|hospital\w*)\b|"
            r"\b(?:infraestructura|cortes?|servicios?|carreteras?|puentes?|"
            r"aeropuertos?|hospitales?)\b|(?:cơ sở hạ tầng|mất điện|đường|cầu|"
            r"インフラ|停電|断水|道路|橋))",
        ),
        (
            InformationNeed.WARNINGS,
            r"(?:\b(?:warning\w*|alert\w*|advisory|advisories|watch|watches)\b|"
            r"\b(?:alertas?|advertencias?|avisos?)\b|(?:cảnh báo|警報|注意報))",
        ),
        (
            InformationNeed.EMERGENCY_RESPONSE,
            r"(?:\b(?:emergency response|response|responders?|relief operations?|"
            r"rescue|government response|aid delivery)\b|"
            r"\b(?:respuesta|rescate|socorro|ayuda)\b|"
            r"(?:ứng phó|cứu hộ|cứu trợ|対応|救助|支援))",
        ),
        (
            InformationNeed.GENERAL_INFORMATION,
            r"(?:\b(?:what causes|why (?:do|does)|how (?:do|does|are|is)|"
            r"definition|in general)\b|\b(?:qué es|por qué|cómo se)\b|"
            r"(?:là gì|tại sao|とは何|なぜ))",
        ),
        (
            InformationNeed.IMAGES,
            r"(?:\b(?:pictures?|images?|photos?|imagery)\b|"
            r"\b(?:fotos?|imágenes?)\b|(?:hình ảnh|画像|写真))",
        ),
        (
            InformationNeed.MAP_VISUALIZATION,
            r"(?:\b(?:map|maps|map layers?|geospatial view)\b|"
            r"\bmapas?\b|(?:bản đồ|地図))",
        ),
        (
            InformationNeed.TIMELINE,
            r"(?:\b(?:timeline|chronology|sequence of events)\b|"
            r"\b(?:cronología|secuencia temporal)\b|"
            r"(?:dòng thời gian|時系列))",
        ),
        (
            InformationNeed.DECISION_SUPPORT,
            r"(?:\b(?:decision support|options?|recommendations?|next steps?|"
            r"what should)\b|\b(?:opciones?|recomendaciones?|próximos pasos|"
            r"qué debería)\b|(?:phương án|khuyến nghị|bước tiếp theo|"
            r"意思決定|選択肢|推奨|次のステップ))",
        ),
    )
    found = tuple(need for need, pattern in patterns if re.search(pattern, text, re.I))
    if InformationNeed.DECISION_SUPPORT in found:
        found = tuple(
            need for need in found if need is not InformationNeed.GENERAL_INFORMATION
        )
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
    return tuple(found[:4])
