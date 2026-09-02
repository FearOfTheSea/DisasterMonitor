from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.agent.investigation_cases import (
    CrossHazardAssessmentStatus,
)
from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentStatus,
    DisasterTaskDraft,
    TaskKind,
)
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    validate_disaster_task,
)
from disaster_monitor.application.agent.tools import ToolDescription, ToolRegistry
from disaster_monitor.application.disaster import (
    DisasterReport,
    EvidencePacket,
    ProviderBatch,
    SelectedEventSummary,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


def test_current_two_hazard_country_request_has_application_owned_targets() -> None:
    catalog = StaticCountryCatalog()
    question = (
        "Investigate the latest earthquake and landslide in Japan, including damage."
    )
    task = validate_disaster_task(
        question,
        deterministic_task_draft(question),
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
    )

    assert task.disaster is None
    assert task.country is not None and task.country.alpha3_code == "JPN"
    assert tuple(target.disaster for target in task.investigation_targets) == (
        Disaster.EARTHQUAKE,
        Disaster.LANDSLIDE,
    )
    assert all(
        target.query.country is task.country for target in task.investigation_targets
    )
    assert all(
        target.query.time_intent == "recent" for target in task.investigation_targets
    )
    assert CrossHazardAssessmentStatus.ASSOCIATED.value == "associated"


def test_two_hazard_requests_fail_closed_for_worldwide_dates_and_extra_hazards() -> (
    None
):
    catalog = StaticCountryCatalog()
    parser = DisasterQueryParser(catalog)
    for question in (
        "Latest earthquake and flood worldwide.",
        "Investigate the earthquake and landslide in Japan on 2026-08-05.",
        "Latest earthquake, flood, and landslide in Japan.",
    ):
        task = validate_disaster_task(
            question,
            deterministic_task_draft(question),
            country_catalog=catalog,
            query_parser=parser,
        )
        assert task.investigation_targets == ()
        assert task.validation_status.value == "clarification_required"


NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


@dataclass
class _TwoHazardWorkflow:
    calls: list[str] = field(default_factory=list)
    fail_disaster: Disaster | None = None

    def registry(self) -> ToolRegistry:
        return ToolRegistry(
            tuple(
                _WorkflowTool(name, self)
                for name in (
                    "list_sources_for_task",
                    "find_disaster_event",
                    "retrieve_situation_evidence",
                    "reconcile_disaster_evidence",
                    "compose_disaster_answer",
                )
            )
        )


class _WorkflowTool:
    def __init__(self, name: str, workflow: _TwoHazardWorkflow) -> None:
        self.workflow = workflow
        self.description = ToolDescription(name, name, (), (), (), (), False)

    async def execute(self, state: AgentExecutionState) -> str:
        task = state.task
        assert task.disaster is not None and task.country is not None
        self.workflow.calls.append(f"{task.disaster.value}:{self.description.name}")
        source = SourceReference(
            f"fixture-{task.disaster.value}",
            "Fixture authority",
            "Fixture event",
            f"https://example.test/{task.disaster.value}",
            NOW,
            NOW,
            NOW,
        )
        event = DisasterEvent(
            f"fixture:{task.disaster.value}",
            task.disaster,
            "Fixture location",
            task.country,
            NOW
            + (
                timedelta(hours=1)
                if task.disaster is Disaster.LANDSLIDE
                else timedelta()
            ),
            source,
            geometry=point_event_geometry(
                35,
                139.2 if task.disaster is Disaster.LANDSLIDE else 139,
                source,
            ),
        )
        if self.description.name == "find_disaster_event":
            if self.workflow.fail_disaster is task.disaster:
                raise RuntimeError("fixture branch failure")
            state.workspace.event_batch = ProviderBatch((event,))
            state.workspace.selected_event = event
        elif self.description.name == "retrieve_situation_evidence":
            state.workspace.situation_batch = ProviderBatch((object(),))
        elif self.description.name == "reconcile_disaster_evidence":
            assert task.query is not None
            state.workspace.evidence_packet = EvidencePacket(
                query=task.query,
                event=event,
                facts=(),
                narratives=(),
                sources=(source,),
                conflicts=(),
                warnings=(),
                retrieved_at=NOW,
                stale=False,
                completeness="event_verified_with_event_specific_evidence",
                partial=False,
            )
        elif self.description.name == "compose_disaster_answer":
            packet = state.workspace.evidence_packet
            assert packet is not None
            state.workspace.report = DisasterReport(
                message="Fixture report",
                response_type="current_disaster",
                selected_event=SelectedEventSummary(
                    event_id=packet.event.event_id,
                    disaster=packet.event.disaster,
                    location=packet.event.location,
                    event_time=packet.event.event_time,
                    geometry=packet.event.geometry,
                    measurements=(),
                    source=packet.event.source,
                    geography_status=packet.event.geography_status,
                ),
                retrieval_time=NOW,
                sources=(source,),
                warnings=(),
                sections=(),
                partial=False,
            )
        return self.description.name


class _InterpretOnlyAgent:
    def __init__(self) -> None:
        self.interpret_calls = 0

    async def interpret(self, question: str) -> DisasterTaskDraft:
        self.interpret_calls += 1
        return DisasterTaskDraft(
            disaster_related=True,
            current_or_event_specific=True,
            task_kind=TaskKind.INVESTIGATION,
            disaster=Disaster.FLOOD,
            country_code="JPN",
            country_name="Japan",
            canonical=True,
        )

    async def propose_plan(self, *args, **kwargs):
        raise AssertionError("Investigation branches must not ask for a model plan.")

    async def review_progress(self, *args, **kwargs):
        raise AssertionError("Investigation branches must not ask for model review.")


@pytest.mark.asyncio
async def test_two_hazard_runtime_reuses_the_pipeline_under_one_shared_budget() -> None:
    catalog = StaticCountryCatalog()
    workflow = _TwoHazardWorkflow()
    model = _InterpretOnlyAgent()
    runtime = DisasterAgentRuntime(
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
        tool_registry=workflow.registry(),
        agent_model=model,
    )

    state = await runtime.run(
        "Did the latest earthquake cause a landslide in Japan? Investigate both."
    )

    assert model.interpret_calls == 1
    assert state.model_call_count == 1
    assert state.tool_call_count == 10
    assert state.replan_count == 0
    assert len(workflow.calls) == 10
    assert workflow.calls[:5] == [
        "earthquake:list_sources_for_task",
        "earthquake:find_disaster_event",
        "earthquake:retrieve_situation_evidence",
        "earthquake:reconcile_disaster_evidence",
        "earthquake:compose_disaster_answer",
    ]
    assert state.workspace.investigation_case is not None
    assert state.workspace.investigation_case.cross_hazard_assessment.status is (
        CrossHazardAssessmentStatus.ASSOCIATED
    )
    assert state.workspace.investigation_case.correlations[0].relationship.value == (
        "spatiotemporal_association"
    )


@pytest.mark.asyncio
async def test_failed_first_branch_retains_its_typed_result_and_runs_the_second() -> (
    None
):
    catalog = StaticCountryCatalog()
    workflow = _TwoHazardWorkflow(fail_disaster=Disaster.EARTHQUAKE)
    runtime = DisasterAgentRuntime(
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
        tool_registry=workflow.registry(),
    )

    state = await runtime.run(
        "Investigate the latest earthquake and landslide in Japan."
    )

    assert state.final_status.value == "partial"
    assert "landslide:compose_disaster_answer" in workflow.calls
    assert state.workspace.investigation_case is not None
    first, second = state.workspace.investigation_case.targets
    assert first.status is AgentStatus.FAILED
    assert second.status is AgentStatus.COMPLETED
    assert state.workspace.investigation_case.cross_hazard_assessment.status is (
        CrossHazardAssessmentStatus.INSUFFICIENT_EVIDENCE
    )
