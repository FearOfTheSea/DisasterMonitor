"""Deterministic classification of disaster requests and requested outputs."""

import re

from disaster_monitor.application.agent.models import (
    DisasterTaskDraft,
    InformationNeed,
    OutputModality,
)
from disaster_monitor.application.disaster import WorldwideDisasterQuery
from disaster_monitor.application.disaster_aliases import recognized_disasters
from disaster_monitor.application.services.disaster_query_parser import (
    has_explicit_date,
)
from disaster_monitor.application.services.worldwide_disaster_policy import (
    WorldwideDisasterPolicyRegistry,
    default_worldwide_disaster_policy_registry,
)
from disaster_monitor.domain.disaster import Disaster

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
