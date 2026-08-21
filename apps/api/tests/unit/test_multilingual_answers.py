from datetime import UTC, datetime

import pytest

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentStatus,
    InvestigationPlan,
    PlanStatus,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.disaster import DisasterReport
from disaster_monitor.application.dto import ModelReadiness, ModelResponse
from disaster_monitor.application.use_cases.run_disaster_agent import RunDisasterAgent
from disaster_monitor.domain.disaster import Disaster


class LocalizerFailure:
    async def interpret(self, question):
        raise AssertionError("interpretation is supplied by the fake runtime")

    async def propose_plan(self, task, tool_descriptions):
        raise AssertionError("planning is supplied by the fake runtime")

    async def review_progress(self, task, completed_steps):
        raise AssertionError("review is supplied by the fake runtime")

    async def localize_grounded_response(self, report, language):
        raise ValueError("localizer unavailable")


class FixedRuntime:
    async def run(self, question: str, **kwargs) -> AgentExecutionState:
        task = ValidatedDisasterTask(
            question,
            TaskKind.INVESTIGATION,
            True,
            disaster=Disaster.EARTHQUAKE,
            response_language="vi",
        )
        state = AgentExecutionState(
            task,
            InvestigationPlan("fixed", question, (), status=PlanStatus.COMPLETED),
        )
        state.workspace.report = DisasterReport(
            message=(
                "## Situation summary\n42 people were affected. "
                "Source: Example Agency (https://example.test/report)."
            ),
            response_type="current_disaster",
            selected_event=None,
            retrieval_time=datetime.now(UTC),
            sources=(),
            warnings=(),
            sections=(),
        )
        state.final_status = AgentStatus.COMPLETED
        return state


class UnusedGeneralModel:
    async def generate(self, request):
        raise AssertionError("general model is not used")


class RecordingGeneralModel:
    def __init__(self) -> None:
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return ModelResponse("回答", "fake-qwen")

    async def check_readiness(self):
        return ModelReadiness(True, True, "fake-qwen")


class GeneralRuntime:
    async def run(self, question: str, **kwargs) -> AgentExecutionState:
        task = ValidatedDisasterTask(
            question,
            TaskKind.GENERAL_KNOWLEDGE,
            False,
            response_language="ko",
            response_language_explicit=True,
        )
        state = AgentExecutionState(
            task,
            InvestigationPlan("general", question, (), status=PlanStatus.COMPLETED),
        )
        state.final_status = AgentStatus.DELEGATED
        return state


@pytest.mark.asyncio
async def test_grounded_answer_is_preserved_when_localization_fails() -> None:
    answer = await RunDisasterAgent(
        FixedRuntime(),
        UnusedGeneralModel(),
        agent_model=LocalizerFailure(),
    ).execute("質問", conversation_id="test")

    assert "42 people were affected" in answer.message


@pytest.mark.asyncio
async def test_explicit_output_language_reaches_general_model_prompt() -> None:
    model = RecordingGeneralModel()
    answer = await RunDisasterAgent(GeneralRuntime(), model).execute(
        "일반적인 설명을 해 주세요.", conversation_id="test"
    )

    assert answer.message == "回答"
    assert "language tag ko" in model.requests[0].messages[0].content
