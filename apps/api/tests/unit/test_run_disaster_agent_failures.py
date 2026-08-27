from datetime import UTC, datetime

import pytest

from disaster_monitor.application.agent.diagnostics import (
    AgentCapability,
    AgentCapabilityDiagnostic,
)
from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentStatus,
    InvestigationPlan,
    PlanStatus,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.disaster import SelectedEventSummary
from disaster_monitor.application.use_cases.run_disaster_agent import RunDisasterAgent
from disaster_monitor.domain.disaster import (
    Disaster,
    EventGeographyStatus,
    SourceReference,
)


class FailedRuntime:
    async def run(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        multimodal_assets=(),
    ) -> AgentExecutionState:
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


class RecordingDiagnostics:
    def __init__(self) -> None:
        self.items: list[AgentCapabilityDiagnostic] = []

    def record(self, diagnostic: AgentCapabilityDiagnostic) -> None:
        self.items.append(diagnostic)


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


@pytest.mark.asyncio
async def test_media_discovery_failure_records_diagnostic_and_preserves_fallback() -> (
    None
):
    now = datetime(2026, 8, 27, tzinfo=UTC)
    source = SourceReference(
        "fixture-source",
        "Fixture",
        "Fixture event",
        "https://example.test/event",
        now,
        now,
        now,
    )
    event = SelectedEventSummary(
        "fixture:event",
        Disaster.EARTHQUAKE,
        "Fixture location",
        now,
        None,
        (),
        source,
        EventGeographyStatus.IN_COUNTRY,
    )

    class FailingMedia:
        async def discover(self, context):
            raise TimeoutError("internal upstream detail")

    diagnostics = RecordingDiagnostics()
    use_case = RunDisasterAgent(
        FailedRuntime(),
        FailIfCalledGeneralModel(),
        event_media=FailingMedia(),
        diagnostics=diagnostics,
    )

    gallery = await use_case._discover_media(
        event, country=None, physical_event_id=None
    )

    assert gallery is None
    assert len(diagnostics.items) == 1
    assert diagnostics.items[0].capability is AgentCapability.EVENT_MEDIA_DISCOVERY
    assert diagnostics.items[0].exception_type == "TimeoutError"
