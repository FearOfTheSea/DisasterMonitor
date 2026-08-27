"""Strict JSON adapter for bounded local-model agent decisions."""

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from disaster_monitor.application.agent.models import (
    AgentReview,
    DisasterTaskDraft,
    InformationNeed,
    InvestigationPlan,
    OutputModality,
    PlanStep,
    ReviewDecision,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.disaster import DisasterReport, GeographicScope
from disaster_monitor.application.dto import ModelMessage, ModelRequest
from disaster_monitor.application.ports.agent_model import AgentModelError
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.domain.disaster import Disaster

MAX_MODEL_JSON = 8_000
MAX_ITEMS = 12
MAX_TEXT = 500
MAX_LOCALIZED_TEXT = 32_000
MAX_LOCALIZATION_TOKENS = 4_096
MAX_LOCALIZATION_CHUNK = 6_000


class StructuredAgentModel:
    """Use an existing language-model port for JSON-only agent operations."""

    def __init__(self, language_model: LanguageModel) -> None:
        self._language_model = language_model

    async def interpret(self, question: str) -> DisasterTaskDraft:
        allowed_needs = ", ".join(item.value for item in InformationNeed)
        allowed_modalities = ", ".join(item.value for item in OutputModality)
        prompt = (
            "Return one JSON object only with exactly these keys: task_kind, disaster, "
            "country_code, country_name, geographic_scope, place_mentions, "
            "current_or_event_specific, date_from, date_to, information_needs, "
            "output_modalities, event_discriminators, requested_response_language, "
            "response_language_explicit, worldwide_selection, clarification_question. "
            "task_kind must be non_disaster, general_knowledge, or investigation. "
            "disaster must be one of earthquake, flood, wildfire, landslide, "
            "tropical_cyclone, volcanic_eruption, or null. geographic_scope must be "
            "country, worldwide, or null for non-disaster/general-knowledge requests. "
            "country_code must be an ISO alpha-3 proposal or "
            "null; country_name must be the corresponding canonical English name or "
            "null. place_mentions must contain bounded place names from the request "
            "for catalog safety, including unsupported names; it must be empty only "
            "when no place is requested. date_from and date_to must be full ISO-8601 "
            "UTC timestamps or null. For an explicit calendar date, always return "
            "both endpoints covering the country's full local calendar day expressed "
            "in UTC; never return only one endpoint. For latest, current, recent, "
            "today, now, or news requests without an explicit date, return null for "
            "both date fields. "
            "requested_response_language must be a short language tag inferred from "
            "the request, or null; do not use a supported-language allowlist. "
            "worldwide_selection must be latest, strongest, or null. Allowed "
            f"information_needs: {allowed_needs}. Allowed output_modalities: "
            f"{allowed_modalities}. event_discriminators must be an empty array unless "
            "a supported canonical discriminator is explicit. Do not emit URLs, code, "
            "provider names, tools, operations, or explanations. The two boolean "
            "fields must contain JSON true or false values, never quoted strings. "
            "All *_question, country_code, country_name, date_from, date_to, and "
            "requested_response_language values are either JSON strings or null; "
            "never arrays or objects. All enum fields are JSON string arrays. "
            "For a current earthquake request in Indonesia, the shape includes "
            "task_kind=investigation, disaster=earthquake, country_code=IDN, "
            "geographic_scope=country, current_or_event_specific=true, "
            "information_needs=[event_overview], output_modalities=[text], "
            "and event_discriminators=[]. Requests for latest, current, recent, news, "
            "or reported information about a supported disaster are investigations, "
            "not general knowledge. Use general_knowledge only for definitions, "
            "causes, mechanisms, or hypothetical/educational questions. Infer the "
            "response language from the user's original text: English uses en, "
            "Vietnamese vi, Chinese zh, Korean ko, and Japanese ja. Do not confuse "
            "Korean or Japanese with Hindi or another language. If the user explicitly "
            "requests a different output language, use that requested language tag. "
            "A named country always uses geographic_scope=country; use worldwide only "
            "when the user explicitly asks for worldwide/global coverage. If a named "
            "country cannot be resolved, keep country scope and return a bounded "
            "country proposal for application catalog validation.\n"
            f"User request: {question}"
        )
        payload = await self._json_with_one_repair(prompt, self._parse_draft)
        return self._parse_draft(payload)

    async def localize_grounded_response(
        self, report: DisasterReport, language: str
    ) -> str:
        if report.sections and len(report.message) > MAX_LOCALIZATION_CHUNK:
            localized_sections: list[str] = []
            for section in report.sections:
                block = f"## {section.title}\n{section.content}"
                for chunk in _bounded_chunks(block, MAX_LOCALIZATION_CHUNK):
                    localized_sections.extend(
                        await self._localize_chunk(chunk, language)
                    )
            return "\n\n".join(localized_sections)
        return (await self._localize_chunk(report.message, language))[0]

    async def _localize_chunk(self, grounded_message: str, language: str) -> list[str]:
        language_name = _language_name(language)
        prompt = (
            "Return one JSON object only with exactly one key: message. Translate the "
            f"grounded report into {language_name} (language tag {language}). Use that "
            "language for all "
            "headings and prose; a copied English response is invalid unless the tag "
            "is en. The tags vi, zh, ko, and ja mean Vietnamese, Chinese, Korean, "
            "and Japanese respectively. Preserve every fact, "
            "number, date, event ID, source name, source title, URL, uncertainty, "
            "and limitation. Do not add, remove, infer, summarize, or correct any "
            "claim. Do not translate URLs, event IDs, or source attribution text. "
            "The application will discard the translation if it is structurally or "
            "factually unsafe.\nGrounded report:\n"
            f"{grounded_message}"
        )
        payload = await self._json_with_one_repair(
            prompt,
            self._parse_localized,
            max_tokens=MAX_LOCALIZATION_TOKENS,
        )
        return [self._parse_localized(payload)]

    async def propose_plan(
        self, task: ValidatedDisasterTask, tool_descriptions: tuple[str, ...]
    ) -> InvestigationPlan:
        tool_names = tuple(item.split(":", 1)[0] for item in tool_descriptions)
        prompt = (
            "Return one JSON object only with required keys plan_id, objective, steps. "
            "steps is an array with step_id, tool_name, purpose, dependencies. "
            "Use at most 8 steps and only these tools: "
            f"{', '.join(tool_names)}. Arguments are application-owned and must not "
            "be included. Do not emit URLs or code.\n"
            f"Task: {task.question}\nTools: {'; '.join(tool_descriptions)}"
        )

        def parser(value: dict[str, Any]) -> InvestigationPlan:
            return self._parse_plan(value, frozenset(tool_names))

        payload = await self._json_with_one_repair(prompt, parser)
        return parser(payload)

    async def review_progress(
        self, task: ValidatedDisasterTask, completed_steps: tuple[str, ...]
    ) -> AgentReview:
        prompt = (
            "Return JSON only with keys decision and detail. decision must be finish, "
            "replan, or clarify. Do not add facts, URLs, code, or hidden reasoning.\n"
            f"Task: {task.question}\nCompleted tools: {', '.join(completed_steps)}"
        )
        payload = await self._json_with_one_repair(prompt, self._parse_review)
        return self._parse_review(payload)

    async def _json_with_one_repair(
        self,
        prompt: str,
        validator: Callable[[dict[str, Any]], object],
        *,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        first = await self._generate(prompt, max_tokens=max_tokens)
        try:
            payload = _json_object(first)
            validator(payload)
            return payload
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            repair_prompt = (
                "Repair the following invalid response into the exact requested JSON "
                "shape. Return JSON only; do not add fields, URLs, code, or prose.\n"
                f"Original instruction: {prompt[:3_500]}\n"
                f"Validation error: {error}\n"
                f"Invalid response: {first[:2_000]}"
            )
        repaired = await self._generate(repair_prompt, max_tokens=max_tokens)
        try:
            payload = _json_object(repaired)
            validator(payload)
            return payload
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise AgentModelError(
                "The local agent model returned invalid structured output."
            ) from error

    async def _generate(self, prompt: str, *, max_tokens: int | None = None) -> str:
        response = await self._language_model.generate(
            ModelRequest(
                (
                    ModelMessage(
                        "system",
                        "You are a bounded request interpreter. "
                        "Output valid JSON only.",
                    ),
                    ModelMessage("user", prompt),
                ),
                max_tokens=max_tokens,
            )
        )
        maximum_response = MAX_LOCALIZED_TEXT if max_tokens else MAX_MODEL_JSON
        if not response.text or len(response.text) > maximum_response:
            raise AgentModelError(
                "The local agent model response was empty or too large."
            )
        return response.text

    @staticmethod
    def _parse_draft(payload: dict[str, Any]) -> DisasterTaskDraft:
        legacy_required = {
            "disaster_related",
            "current_or_event_specific",
            "disaster_mentions",
            "place_mentions",
            "time_expression",
            "information_needs",
            "output_modalities",
            "event_discriminators",
            "ambiguities",
            "clarification_question",
        }
        canonical_required = {
            "task_kind",
            "disaster",
            "country_code",
            "country_name",
            "geographic_scope",
            "place_mentions",
            "current_or_event_specific",
            "date_from",
            "date_to",
            "information_needs",
            "output_modalities",
            "event_discriminators",
            "requested_response_language",
            "response_language_explicit",
            "worldwide_selection",
            "clarification_question",
        }
        if set(payload) == legacy_required:
            return _parse_legacy_draft(payload)
        _exact_keys(payload, canonical_required)
        if not isinstance(payload["current_or_event_specific"], bool):
            raise ValueError("Agent current-intent flag is invalid.")
        if not isinstance(payload["response_language_explicit"], bool):
            raise ValueError("Agent response-language flag is invalid.")
        task_kind = TaskKind(_text(payload["task_kind"]))
        disaster = _optional_enum(payload["disaster"], Disaster)
        geographic_scope = _optional_enum(payload["geographic_scope"], GeographicScope)
        needs = _enum_strings(payload["information_needs"], InformationNeed)
        modalities = _enum_strings(payload["output_modalities"], OutputModality)
        selection = payload["worldwide_selection"]
        if isinstance(selection, str) and not selection.strip():
            selection = None
        if selection is not None and selection not in {"latest", "strongest"}:
            raise ValueError("Unsupported worldwide selection.")
        return DisasterTaskDraft(
            disaster_related=task_kind is not TaskKind.NON_DISASTER,
            current_or_event_specific=payload["current_or_event_specific"],
            place_mentions=_strings(payload["place_mentions"]),
            information_needs=needs,
            output_modalities=modalities,
            event_discriminators=_strings(payload["event_discriminators"]),
            clarification_question=_optional_text(payload["clarification_question"]),
            task_kind=task_kind,
            disaster=disaster,
            country_code=_optional_text(payload["country_code"]),
            country_name=_optional_text(payload["country_name"]),
            geographic_scope=geographic_scope,
            date_from=_optional_text(payload["date_from"]),
            date_to=_optional_text(payload["date_to"]),
            requested_response_language=_optional_text(
                _language_tag(payload["requested_response_language"])
                if payload["requested_response_language"] is not None
                else None
            ),
            response_language_explicit=payload["response_language_explicit"],
            worldwide_selection=selection,
            canonical=True,
        )

    @staticmethod
    def _parse_localized(payload: dict[str, Any]) -> str:
        _exact_keys(payload, {"message"})
        value = payload["message"]
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > MAX_LOCALIZED_TEXT
        ):
            raise ValueError("Invalid localized response.")
        return value.strip()

    @staticmethod
    def _parse_plan(
        payload: dict[str, Any], allowed_tools: frozenset[str]
    ) -> InvestigationPlan:
        _exact_keys(payload, {"plan_id", "objective", "steps"})
        raw_steps = payload["steps"]
        if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 8:
            raise ValueError("Invalid plan steps.")
        steps = []
        for raw in raw_steps:
            if not isinstance(raw, dict):
                raise ValueError("Invalid plan step.")
            _exact_keys(raw, {"step_id", "tool_name", "purpose", "dependencies"})
            tool_name = _text(raw["tool_name"])
            if tool_name not in allowed_tools:
                raise ValueError("Unknown tool name.")
            steps.append(
                PlanStep(
                    _text(raw["step_id"]),
                    tool_name,
                    (),
                    _text(raw["purpose"]),
                    _strings(raw["dependencies"]),
                )
            )
        return InvestigationPlan(
            _text(payload["plan_id"]), _text(payload["objective"]), tuple(steps)
        )

    @staticmethod
    def _parse_review(payload: dict[str, Any]) -> AgentReview:
        _exact_keys(payload, {"decision", "detail"})
        return AgentReview(
            ReviewDecision(_text(payload["decision"])), _text(payload["detail"])
        )

    async def aclose(self) -> None:
        close = getattr(self._language_model, "aclose", None)
        if close is not None:
            result: Awaitable[None] = close()
            await result


def _json_object(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Expected one JSON object.")
    return payload


def _exact_keys(payload: dict[str, Any], required: set[str]) -> None:
    if set(payload) != required:
        raise ValueError("Unexpected or missing structured-output fields.")


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError(f"Invalid bounded text type: {type(value).__name__}.")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return _text(value)


def _optional_enum(value: object, enum_type: type) -> Any:
    return None if value is None else enum_type(_text(value))


def _language_tag(value: object) -> str:
    tag = _text(value)
    if not re.fullmatch(r"[A-Za-z]{2,12}(?:[-_][A-Za-z0-9]{2,12})?", tag):
        raise ValueError("Invalid response language tag.")
    return tag


def _language_name(tag: str) -> str:
    prefix = tag.casefold().replace("_", "-").split("-", 1)[0]
    return {
        "en": "English",
        "vi": "Vietnamese",
        "zh": "Chinese",
        "ko": "Korean",
        "ja": "Japanese",
    }.get(prefix, f"the language identified by {tag}")


def _bounded_chunks(text: str, maximum: int) -> tuple[str, ...]:
    if len(text) <= maximum:
        return (text,)
    chunks: list[str] = []
    remaining = text
    while len(remaining) > maximum:
        split_at = remaining.rfind("\n\n", 0, maximum)
        if split_at < maximum // 2:
            split_at = remaining.rfind("\n", 0, maximum)
        if split_at < maximum // 2:
            split_at = maximum
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return tuple(chunk for chunk in chunks if chunk)


def _parse_legacy_draft(payload: dict[str, Any]) -> DisasterTaskDraft:
    if not isinstance(payload["disaster_related"], bool) or not isinstance(
        payload["current_or_event_specific"], bool
    ):
        raise ValueError("Agent booleans are invalid.")
    return DisasterTaskDraft(
        disaster_related=payload["disaster_related"],
        current_or_event_specific=payload["current_or_event_specific"],
        disaster_mentions=_strings(payload["disaster_mentions"]),
        place_mentions=_strings(payload["place_mentions"]),
        time_expression=_optional_text(payload["time_expression"]),
        information_needs=_enum_strings(payload["information_needs"], InformationNeed),
        output_modalities=_enum_strings(payload["output_modalities"], OutputModality),
        event_discriminators=_strings(payload["event_discriminators"]),
        ambiguities=_strings(payload["ambiguities"]),
        clarification_question=_optional_text(payload["clarification_question"]),
    )


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError("Invalid bounded list.")
    return tuple(_text(item) for item in value)


def _enum_strings(value: object, enum_type: type) -> tuple[str, ...]:
    items = _strings(value)
    for item in items:
        enum_type(item)
    return items
