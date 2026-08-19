import json
from dataclasses import dataclass, field

import pytest

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
