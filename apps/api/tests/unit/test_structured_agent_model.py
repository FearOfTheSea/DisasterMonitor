import json
from dataclasses import dataclass, field

import pytest

from disaster_monitor.application.agent.models import (
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.agent.sufficiency import (
    EvidenceGapCode,
    EvidenceSufficiencyAssessment,
    EvidenceSufficiencyState,
    FollowUpOption,
)
from disaster_monitor.application.dto import (
    ModelReadiness,
    ModelRequest,
    ModelResponse,
)
from disaster_monitor.application.ports.agent_model import AgentModelError
from disaster_monitor.infrastructure.llm.structured_agent_model import (
    StructuredAgentModel,
)


@dataclass
class SequenceModel:
    responses: list[str]
    requests: list[ModelRequest] = field(default_factory=list)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.responses.pop(0), "fake-agent")

    async def check_readiness(self) -> ModelReadiness:
        return ModelReadiness(True, True, "fake-agent")


def valid_draft() -> dict[str, object]:
    return {
        "disaster_related": True,
        "current_or_event_specific": True,
        "disaster_mentions": ["earthquake"],
        "place_mentions": ["Japan"],
        "time_expression": "August 5, 2026",
        "information_needs": ["fatalities"],
        "output_modalities": ["focused_fact"],
        "event_discriminators": ["August 5, 2026"],
        "ambiguities": [],
        "clarification_question": None,
    }


def canonical_draft() -> dict[str, object]:
    return {
        "task_kind": "investigation",
        "disaster": "earthquake",
        "country_code": "JPN",
        "country_name": "Japan",
        "geographic_scope": "country",
        "place_mentions": ["Japan"],
        "current_or_event_specific": True,
        "date_from": None,
        "date_to": None,
        "information_needs": ["event_overview"],
        "output_modalities": ["text"],
        "event_discriminators": [],
        "requested_response_language": "ja",
        "response_language_explicit": False,
        "worldwide_selection": None,
        "clarification_question": None,
    }


@pytest.mark.asyncio
async def test_agent_json_is_strictly_parsed() -> None:
    model = SequenceModel([json.dumps(valid_draft())])
    result = await StructuredAgentModel(model).interpret("Latest earthquake in Japan")

    assert result.disaster_mentions == ("earthquake",)
    assert result.information_needs == ("fatalities",)
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_agent_json_gets_exactly_one_bounded_repair_attempt() -> None:
    model = SequenceModel(["not-json", json.dumps(valid_draft())])

    result = await StructuredAgentModel(model).interpret("Latest earthquake in Japan")

    assert result.disaster_related
    assert len(model.requests) == 2


@pytest.mark.asyncio
async def test_agent_json_rejects_unknown_enums_and_fields_after_repair() -> None:
    invalid = valid_draft()
    invalid["output_modalities"] = ["execute_python"]
    extra = {**valid_draft(), "url": "https://untrusted.example"}
    model = SequenceModel([json.dumps(invalid), json.dumps(extra)])

    with pytest.raises(AgentModelError):
        await StructuredAgentModel(model).interpret("Latest earthquake in Japan")

    assert len(model.requests) == 2


@pytest.mark.asyncio
async def test_agent_json_parses_canonical_semantics_and_response_language() -> None:
    model = SequenceModel([json.dumps(canonical_draft())])

    result = await StructuredAgentModel(model).interpret("日本語の質問")

    assert result.canonical is True
    assert result.disaster.value == "earthquake"
    assert result.country_code == "JPN"
    assert result.requested_response_language == "ja"


@pytest.mark.asyncio
async def test_agent_json_allows_null_scope_for_general_knowledge() -> None:
    draft = canonical_draft()
    draft.update(
        {
            "task_kind": "general_knowledge",
            "disaster": None,
            "country_code": None,
            "country_name": None,
            "geographic_scope": None,
            "current_or_event_specific": False,
            "information_needs": [],
        }
    )
    model = SequenceModel([json.dumps(draft)])

    result = await StructuredAgentModel(model).interpret("一般的な質問")

    assert result.task_kind.value == "general_knowledge"
    assert result.disaster is None
    assert result.geographic_scope is None


@pytest.mark.asyncio
async def test_grounded_localization_is_a_separate_strict_operation() -> None:
    model = SequenceModel(
        [json.dumps({"message": "## 概要\n42 people. Source: https://example.test"})]
    )
    report = type(
        "Report",
        (),
        {
            "message": "## Summary\n42 people. Source: https://example.test",
            "sections": (),
        },
    )()

    result = await StructuredAgentModel(model).localize_grounded_response(report, "ja")

    assert "42" in result
    assert "https://example.test" in result


@pytest.mark.asyncio
async def test_review_json_can_select_only_the_supplied_followup_option() -> None:
    model = SequenceModel(
        [
            json.dumps(
                {
                    "decision": "replan",
                    "detail": "Retry the bounded evidence stage.",
                    "selected_follow_up_option_id": "retry_situation_evidence",
                }
            )
        ]
    )
    task = ValidatedDisasterTask("test", TaskKind.INVESTIGATION, True)
    assessment = EvidenceSufficiencyAssessment(
        EvidenceSufficiencyState.FOLLOWUP_AVAILABLE,
        (EvidenceGapCode.RETRYABLE_SITUATION_EVIDENCE,),
        (FollowUpOption("retry_situation_evidence", "bounded retry"),),
    )

    result = await StructuredAgentModel(model).review_progress(task, assessment)

    assert result.selected_follow_up_option_id == "retry_situation_evidence"
    assert "Permitted follow-up options" in model.requests[0].messages[1].content


@pytest.mark.asyncio
async def test_review_json_rejects_a_model_invented_followup_option() -> None:
    invalid = {
        "decision": "replan",
        "detail": "Retry it.",
        "selected_follow_up_option_id": "invented_provider_retry",
    }
    model = SequenceModel([json.dumps(invalid), json.dumps(invalid)])
    task = ValidatedDisasterTask("test", TaskKind.INVESTIGATION, True)
    assessment = EvidenceSufficiencyAssessment(
        EvidenceSufficiencyState.FOLLOWUP_AVAILABLE,
        (EvidenceGapCode.RETRYABLE_SITUATION_EVIDENCE,),
        (FollowUpOption("retry_situation_evidence", "bounded retry"),),
    )

    with pytest.raises(AgentModelError):
        await StructuredAgentModel(model).review_progress(task, assessment)

    assert len(model.requests) == 2
