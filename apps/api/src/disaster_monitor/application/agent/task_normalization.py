"""Deterministic safety gating and canonical disaster-task validation."""

import re

from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    InformationNeed,
    OutputModality,
    TaskKind,
    ValidatedDisasterTask,
    ValidationStatus,
)
from disaster_monitor.application.disaster import (
    GlobalEarthquakeQuery,
    GlobalEventSelection,
    QueryParseStatus,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import Hazard

_HAZARDS: dict[Hazard, tuple[str, ...]] = {
    Hazard.EARTHQUAKE: (
        "earthquake",
        "earthquakes",
        "quake",
        "quakes",
        "terremoto",
        "terremotos",
        "động đất",
        "地震",
    ),
    Hazard.TSUNAMI: ("tsunami", "tsunamis", "sóng thần", "津波"),
    Hazard.FLOOD: (
        "flood",
        "floods",
        "flooding",
        "inundación",
        "inundaciones",
        "lũ lụt",
        "洪水",
    ),
    Hazard.WILDFIRE: (
        "wildfire",
        "wildfires",
        "forest fire",
        "incendio forestal",
        "cháy rừng",
        "山火事",
    ),
    Hazard.LANDSLIDE: (
        "landslide",
        "landslides",
        "deslizamiento de tierra",
        "sạt lở đất",
        "地滑り",
    ),
    Hazard.TROPICAL_CYCLONE: (
        "typhoon",
        "hurricane",
        "cyclone",
        "tropical cyclone",
        "tifón",
        "huracán",
        "bão nhiệt đới",
        "台風",
    ),
}
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
_EVENT_DATE_MARKER = re.compile(
    r"\b(?:20\d{2}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]20\d{2}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*20\d{2})\b",
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
_STRONGEST_MARKERS = re.compile(
    r"\b(?:strongest|largest|biggest|highest[- ]magnitude|most powerful)\b", re.I
)


def global_earthquake_query(question: str) -> GlobalEarthquakeQuery | None:
    """Admit only explicit current worldwide earthquake requests."""
    hazards = _hazard_mentions(question)
    if (
        hazards != (Hazard.EARTHQUAKE,)
        or not disaster_safety_gate(question)
        or not _WORLDWIDE_MARKERS.search(question)
    ):
        return None
    return GlobalEarthquakeQuery(
        selection=(
            GlobalEventSelection.STRONGEST
            if _STRONGEST_MARKERS.search(question)
            else GlobalEventSelection.LATEST
        )
    )


def disaster_safety_gate(question: str) -> bool:
    """Conservatively retain factual disaster requests in the trusted path."""
    hazards = _hazard_mentions(question)
    if not hazards:
        return False
    if _CURRENT_EVENT_MARKERS.search(question) or _EVENT_DATE_MARKER.search(question):
        return True
    if _GENERAL_KNOWLEDGE_MARKERS.search(question):
        return False
    return bool(_EVIDENCE_MARKERS.search(question))


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
    if not deterministic_hazards:
        return ValidatedDisasterTask(
            question, TaskKind.NON_DISASTER, False, information_needs=()
        )
    hazards = deterministic_hazards
    requires_evidence = safety_requires_evidence
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
    needs = _information_needs(question)
    modalities = _output_modalities(question)
    return ValidatedDisasterTask(
        question=question,
        kind=TaskKind.INVESTIGATION,
        requires_evidence=True,
        hazard=hazards[0],
        country=countries[0],
        date_from=parsed.query.date_from,
        date_to=parsed.query.date_to,
        event_discriminators=(),
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


def _hazard_mentions(text: str) -> tuple[Hazard, ...]:
    return tuple(
        hazard
        for hazard, aliases in _HAZARDS.items()
        if any(_matches_alias(text, alias) for alias in aliases)
    )


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


def _matches_alias(text: str, alias: str) -> bool:
    boundary = r"[A-Za-z0-9_]" if not alias.isascii() else r"\w"
    return bool(
        re.search(rf"(?<!{boundary}){re.escape(alias)}(?!{boundary})", text, re.I)
    )


def _extract_raw_places(text: str) -> tuple[str, ...]:
    found = [match.group(1).strip() for match in _PLACE_AFTER_IN.finditer(text)]
    return tuple(found[:4])
