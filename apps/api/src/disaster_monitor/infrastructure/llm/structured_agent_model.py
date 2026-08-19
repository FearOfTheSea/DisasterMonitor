"""Strict JSON adapter for bounded local-model agent decisions."""

import json
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
    ValidatedDisasterTask,
)
from disaster_monitor.application.dto import ModelMessage, ModelRequest
from disaster_monitor.application.ports.agent_model import AgentModelError
from disaster_monitor.application.ports.language_model import LanguageModel

MAX_MODEL_JSON = 8_000
MAX_ITEMS = 12
MAX_TEXT = 500


class StructuredAgentModel:
    """Use an existing language-model port for JSON-only agent operations."""

    def __init__(self, language_model: LanguageModel) -> None:
        self._language_model = language_model

    async def interpret(self, question: str) -> DisasterTaskDraft:
        allowed_needs = ", ".join(item.value for item in InformationNeed)
        allowed_modalities = ", ".join(item.value for item in OutputModality)
        prompt = (
            "Return one JSON object only. Required keys: disaster_related (boolean), "
            "current_or_event_specific (boolean), disaster_mentions (string array), "
            "place_mentions (string array), time_expression (string or null), "
            "information_needs (array), output_modalities (array), "
            "event_discriminators (string array), ambiguities (string array), "
            "clarification_question (string or null). Allowed information_needs: "
            f"{allowed_needs}. Allowed output_modalities: {allowed_modalities}. "
            "Do not emit URLs, code, provider names, country codes, or explanations.\n"
            f"User request: {question}"
        )
        payload = await self._json_with_one_repair(prompt, self._parse_draft)
        return self._parse_draft(payload)

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
    ) -> dict[str, Any]:
        first = await self._generate(prompt)
        try:
            payload = _json_object(first)
            validator(payload)
            return payload
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            repair_prompt = (
                "Repair the following invalid response into the exact requested JSON "
                "shape. Return JSON only; do not add fields, URLs, code, or prose.\n"
                f"Original instruction: {prompt[:3_500]}\n"
                f"Invalid response: {first[:2_000]}"
            )
        repaired = await self._generate(repair_prompt)
        try:
            payload = _json_object(repaired)
            validator(payload)
            return payload
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise AgentModelError(
                "The local agent model returned invalid structured output."
            ) from error

    async def _generate(self, prompt: str) -> str:
        response = await self._language_model.generate(
            ModelRequest(
                (
                    ModelMessage(
                        "system",
                        "You are a bounded request interpreter. "
                        "Output valid JSON only.",
                    ),
                    ModelMessage("user", prompt),
                )
            )
        )
        if not response.text or len(response.text) > MAX_MODEL_JSON:
            raise AgentModelError(
                "The local agent model response was empty or too large."
            )
        return response.text

    @staticmethod
    def _parse_draft(payload: dict[str, Any]) -> DisasterTaskDraft:
        required = {
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
        _exact_keys(payload, required)
        if not isinstance(payload["disaster_related"], bool) or not isinstance(
            payload["current_or_event_specific"], bool
        ):
            raise ValueError("Agent booleans are invalid.")
        needs = _enum_strings(payload["information_needs"], InformationNeed)
        modalities = _enum_strings(payload["output_modalities"], OutputModality)
        return DisasterTaskDraft(
            disaster_related=payload["disaster_related"],
            current_or_event_specific=payload["current_or_event_specific"],
            disaster_mentions=_strings(payload["disaster_mentions"]),
            place_mentions=_strings(payload["place_mentions"]),
            time_expression=_optional_text(payload["time_expression"]),
            information_needs=needs,
            output_modalities=modalities,
            event_discriminators=_strings(payload["event_discriminators"]),
            ambiguities=_strings(payload["ambiguities"]),
            clarification_question=_optional_text(payload["clarification_question"]),
        )

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
        raise ValueError("Invalid bounded text.")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError("Invalid bounded list.")
    return tuple(_text(item) for item in value)


def _enum_strings(value: object, enum_type: type) -> tuple[str, ...]:
    items = _strings(value)
    for item in items:
        enum_type(item)
    return items
