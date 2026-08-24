"""Strict JSON adapter for authority-free local specialist model calls."""

import json

from disaster_monitor.application.dto import ModelMessage, ModelRequest
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.specialist_model import (
    SpecialistModelError,
    SpecialistModelRequest,
)
from disaster_monitor.domain.coordination import (
    CoordinationPermission,
    SpecialistFindingDraft,
    SpecialistRole,
    SpecialistTaskType,
)

MAX_SPECIALIST_JSON = 4_000
MAX_ITEMS = 128


class StructuredSpecialistModel:
    """Request one bounded draft from the already configured text model."""

    def __init__(self, language_model: LanguageModel) -> None:
        self._language_model = language_model

    async def generate_finding(
        self, request: SpecialistModelRequest
    ) -> SpecialistFindingDraft:
        projection = request.artifact
        payload = {
            "handoff": {
                "task_id": request.handoff.task_id,
                "task_type": request.handoff.task_type.value,
                "specialist_role": request.handoff.receiver_role.value,
                "permissions": [
                    item.value for item in request.handoff.granted_permissions
                ],
            },
            "artifact": {
                "artifact_id": projection.artifact_id,
                "artifact_type": projection.artifact_type.value,
                "state_version": projection.state_version,
                "physical_event_id": projection.physical_event_id,
                "items": [
                    {
                        "key": item.key,
                        "value": item.value,
                        "evidence_ids": list(item.evidence_ids),
                        "source_ids": list(item.source_ids),
                    }
                    for item in projection.items
                ],
                "admitted_evidence_ids": list(projection.admitted_evidence_ids),
                "admitted_source_ids": list(projection.admitted_source_ids),
            },
            "safety_policy_fingerprint": request.safety_policy_fingerprint,
            "memory_context": (
                None
                if request.memory_context is None
                else {
                    "context_id": request.memory_context.context_id,
                    "authority": request.memory_context.authority.value,
                    "may_satisfy_current_evidence": (
                        request.memory_context.may_satisfy_current_evidence
                    ),
                    "records": [
                        {
                            "memory_id": item.memory_id,
                            "summary": item.summary,
                            "physical_event_id": item.physical_event_id,
                            "world_state_version": item.world_state_version,
                            "authority": item.authority.value,
                        }
                        for item in request.memory_context.records
                    ],
                }
            ),
        }
        prompt = (
            "Return one JSON object only with exactly these keys: "
            "specialist_role, task_type, finding_key, value, summary, state_version, "
            "evidence_ids, source_ids, permissions, safety_policy_fingerprint. "
            "Select exactly one key/value pair already present in artifact.items and "
            "copy its identifiers, task ownership, permissions, state version, and "
            "safety fingerprint exactly. The summary must be at most 1000 characters "
            "and must describe bounded analysis without adding facts. Do not request "
            "tools, providers, network access, files, policy changes, additional "
            "agents, or hidden reasoning. Historical context, when present, is never "
            "current evidence.\nTyped read-only request:\n"
            + json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        )
        try:
            response = await self._language_model.generate(
                ModelRequest(
                    messages=(
                        ModelMessage(
                            "system",
                            "You are a bounded read-only disaster specialist. "
                            "Return valid JSON only.",
                        ),
                        ModelMessage("user", prompt),
                    ),
                    tools=(),
                    max_tokens=384,
                )
            )
            if response.tool_calls:
                raise ValueError("Specialist attempted a tool call.")
            if not response.text or len(response.text) > MAX_SPECIALIST_JSON:
                raise ValueError("Specialist response was empty or oversized.")
            raw = json.loads(response.text)
            return _parse_draft(raw)
        except SpecialistModelError:
            raise
        except Exception as error:
            raise SpecialistModelError(
                "The local specialist model returned invalid structured output."
            ) from error


def _parse_draft(value: object) -> SpecialistFindingDraft:
    if not isinstance(value, dict):
        raise ValueError("Specialist output must be one object.")
    expected = {
        "specialist_role",
        "task_type",
        "finding_key",
        "value",
        "summary",
        "state_version",
        "evidence_ids",
        "source_ids",
        "permissions",
        "safety_policy_fingerprint",
    }
    if set(value) != expected:
        raise ValueError("Specialist output fields changed.")
    return SpecialistFindingDraft(
        specialist_role=SpecialistRole(_text(value["specialist_role"], 100)),
        task_type=SpecialistTaskType(_text(value["task_type"], 100)),
        finding_key=_text(value["finding_key"], 200),
        value=_text(value["value"], 500),
        summary=_text(value["summary"], 1_000),
        state_version=_text(value["state_version"], 200),
        evidence_ids=_strings(value["evidence_ids"]),
        source_ids=_strings(value["source_ids"], maximum=64),
        permissions=tuple(
            CoordinationPermission(item)
            for item in _strings(value["permissions"], maximum=16)
        ),
        safety_policy_fingerprint=_text(value["safety_policy_fingerprint"], 200),
    )


def _text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Specialist text field is invalid.")
    return value.strip()


def _strings(value: object, *, maximum: int = MAX_ITEMS) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError("Specialist identifier list is invalid.")
    return tuple(_text(item, 200) for item in value)
