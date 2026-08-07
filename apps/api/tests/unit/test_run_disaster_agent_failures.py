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


class FailedRuntime:
    async def run(self, question: str) -> AgentExecutionState:
        task = ValidatedDisasterTask(question, TaskKind.INVESTIGATION, True)
        plan = InvestigationPlan(
            "failed-plan",
            question,
            (),
            status=PlanStatus.FAILED,
        )
        state = AgentExecutionState(task, plan)
        state.final_status = AgentStatus.FAILED
        state.termination_reason = "tool_execution_failed"
        state.warnings.append("The bounded investigation stopped safely.")
        return state


class FailIfCalledGeneralModel:
    async def generate(self, request):
        raise AssertionError("General model must not answer a failed investigation.")


@pytest.mark.asyncio
async def test_failed_investigation_is_not_reported_as_coverage_unavailable() -> None:
    use_case = RunDisasterAgent(FailedRuntime(), FailIfCalledGeneralModel())

    answer = await use_case.execute(
        "Give me the latest earthquake information in Japan.",
        conversation_id="test-session",
    )

    assert answer.response_type == "current_disaster_investigation_failed"
    assert answer.model == "disaster-agent"
    assert answer.partial is True
    assert answer.investigation is not None
    assert answer.investigation.status == "failed"
    assert answer.investigation.termination_reason == "tool_execution_failed"
