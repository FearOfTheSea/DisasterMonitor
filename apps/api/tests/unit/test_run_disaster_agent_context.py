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
from disaster_monitor.application.use_cases.run_disaster_agent import RunDisasterAgent
from disaster_monitor.domain.conversation import ConversationMessage, ConversationRole
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


def _catalog() -> StaticCountryCatalog:
    result = StaticCountryCatalog()
    result.activate_payload(
        {
            "metadata": {"version": "agent-context-test"},
            "countries": [
                {
                    "alpha3": "THA",
                    "name": "Thailand",
                    "aliases": ["TH"],
                    "timezone": "Asia/Bangkok",
                    "bounds": [5.5, 20.5, 97.3, 105.7],
                    "polygons": [],
                },
                {
                    "alpha3": "VNM",
                    "name": "Vietnam",
                    "aliases": ["VN"],
                    "timezone": "Asia/Ho_Chi_Minh",
                    "bounds": [8.2, 23.4, 102.1, 109.5],
                    "polygons": [],
                },
            ],
        }
    )
    return result


class RecordingRuntime:
    def __init__(self) -> None:
        self.questions: list[str] = []

    async def run(self, question: str, **kwargs) -> AgentExecutionState:
        del kwargs
        self.questions.append(question)
        task = ValidatedDisasterTask(question, TaskKind.INVESTIGATION, True)
        state = AgentExecutionState(
            task,
            InvestigationPlan("test-plan", question, (), status=PlanStatus.COMPLETED),
        )
        state.final_status = AgentStatus.CLARIFICATION_REQUIRED
        state.termination_reason = "test"
        state.capability_gaps.append("test")
        return state


class UnusedGeneralModel:
    async def generate(self, request):
        raise AssertionError("The general model is not expected for this test.")


def user_message(content: str) -> ConversationMessage:
    return ConversationMessage(
        "m1", "conversation-a", ConversationRole.USER, content, datetime.now(UTC)
    )


@pytest.mark.asyncio
async def test_safe_follow_up_reaches_runtime_as_resolved_context() -> None:
    runtime = RecordingRuntime()
    use_case = RunDisasterAgent(
        runtime,
        UnusedGeneralModel(),
        country_catalog=_catalog(),
    )

    await use_case.execute(
        "What about Vietnam?",
        conversation_id="conversation-a",
        conversation_history=(user_message("What are the latest floods in Thailand?"),),
    )

    assert len(runtime.questions) == 1
    assert "flood" in runtime.questions[0].lower()
    assert "Vietnam" in runtime.questions[0]
    assert "Thailand" not in runtime.questions[0]


@pytest.mark.asyncio
async def test_non_resolvable_turn_reaches_runtime_unchanged() -> None:
    runtime = RecordingRuntime()
    use_case = RunDisasterAgent(
        runtime,
        UnusedGeneralModel(),
        country_catalog=_catalog(),
    )

    await use_case.execute(
        "Tell me about Vietnam.",
        conversation_id="conversation-a",
        conversation_history=(user_message("What are the latest floods in Thailand?"),),
    )

    assert runtime.questions == ["Tell me about Vietnam."]
