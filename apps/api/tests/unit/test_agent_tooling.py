from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    AgentReview,
    DisasterTaskDraft,
    InformationNeed,
    InvestigationPlan,
    OutputModality,
    PlanStep,
    ReviewDecision,
    SourceDescriptor,
    SourceInformationRole,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.agent.planning import (
    default_investigation_plan,
    validate_plan,
)
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.agent.tooling import (
    DisasterToolDependencies,
    ToolDescription,
    ToolRegistry,
    build_disaster_tool_registry,
    execute_plan,
)
from disaster_monitor.application.disaster import (
    DisasterQuery,
    GeographicScope,
    ProviderBatch,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_consistency import (
    validate_provider_source_consistency,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    GeographicArea,
    SourceReference,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


class DummyTool:
    description = ToolDescription("dummy", "test tool", (), (), (), (), False)

    async def execute(self, state: AgentExecutionState) -> str:
        return "ran dummy"


class NamedTool:
    def __init__(self, name: str) -> None:
        self.description = ToolDescription(name, "test tool", (), (), (), (), False)

    async def execute(self, state: AgentExecutionState) -> str:
        return "ran named tool"


def test_tool_registry_rejects_duplicate_and_unknown_names() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        ToolRegistry((DummyTool(), DummyTool()))
    registry = ToolRegistry((DummyTool(),))
    with pytest.raises(ValueError, match="Unknown"):
        registry.resolve("generated_python_tool")


def test_plan_validation_rejects_unknown_tools_and_invalid_dependencies() -> None:
    unknown = InvestigationPlan(
        "p",
        "test",
        (PlanStep("one", "generated_python_tool", (), "unsafe"),),
    )
    sequencing = InvestigationPlan(
        "p",
        "test",
        (PlanStep("one", "dummy", (), "bad", ("missing",)),),
    )
    with pytest.raises(ValueError, match="Unknown"):
        validate_plan(unknown, allowed_tools=frozenset({"dummy"}))
    with pytest.raises(ValueError, match="sequencing"):
        validate_plan(sequencing, allowed_tools=frozenset({"dummy"}))


@pytest.mark.asyncio
async def test_tool_execution_enforces_call_budget() -> None:
    country = Country("TST", "Testland", (), GeographicArea(0, 1, 0, 1), "UTC")
    query = DisasterQuery(Disaster.FLOOD, country, "recent", ("latest",))
    task = ValidatedDisasterTask(
        "test",
        TaskKind.INVESTIGATION,
        True,
        Disaster.FLOOD,
        country,
        query=query,
    )
    steps = tuple(
        PlanStep(
            f"s{index}",
            "dummy",
            (),
            "bounded",
            () if index == 0 else (f"s{index - 1}",),
        )
        for index in range(13)
    )
    state = AgentExecutionState(task, InvestigationPlan("p", "test", steps, 20))

    with pytest.raises(RuntimeError, match="budget"):
        await execute_plan(state, ToolRegistry((DummyTool(),)))

    assert state.tool_call_count == 12


@pytest.mark.asyncio
async def test_skipped_plan_steps_keep_distinct_purpose_in_actions() -> None:
    country = Country("TST", "Testland", (), GeographicArea(0, 1, 0, 1), "UTC")
    query = DisasterQuery(Disaster.FLOOD, country, "recent", ("latest",))
    task = ValidatedDisasterTask(
        "Latest flood in Testland",
        TaskKind.INVESTIGATION,
        True,
        Disaster.FLOOD,
        country,
        query=query,
    )
    plan = InvestigationPlan(
        "skipped",
        task.question,
        (
            PlanStep("retrieve", "retrieve_situation_evidence", (), "retrieve impacts"),
            PlanStep(
                "reconcile",
                "reconcile_disaster_evidence",
                (),
                "reconcile impacts",
                ("retrieve",),
            ),
        ),
    )
    state = AgentExecutionState(task, plan)

    await execute_plan(
        state,
        ToolRegistry(
            (
                NamedTool("retrieve_situation_evidence"),
                NamedTool("reconcile_disaster_evidence"),
            )
        ),
    )

    assert [action.description for action in state.actions] == [
        "Skipped step retrieve (retrieve impacts): no selected event was available.",
        "Skipped step reconcile (reconcile impacts): no selected event was available.",
    ]


@dataclass
class FakeCatalog:
    descriptor: SourceDescriptor
    version: str = "test"

    def sources(self) -> tuple[SourceDescriptor, ...]:
        return (self.descriptor,)

    def get(self, source_id: str) -> SourceDescriptor | None:
        return self.descriptor if source_id == self.descriptor.source_id else None


class NewFloodProvider:
    provider_name = "Testland flood authority"

    def __init__(self, event: DisasterEvent) -> None:
        self.event = event
        self.calls = 0

    async def find_recent_events(self, query, *, now):
        self.calls += 1
        return ProviderBatch((self.event,))


class EmptySituationProvider:
    async def get_situation_reports(self, event, query, *, now):
        return ProviderBatch()


@pytest.mark.asyncio
async def test_new_country_and_disaster_provider_is_discovered_without_agent_branch():
    country = Country("TST", "Testland", (), GeographicArea(0, 10, 0, 10), "UTC")
    source = SourceReference(
        "testland-floods",
        "Test authority",
        "Flood event",
        "https://example.test/flood",
        NOW,
        NOW,
        NOW,
    )
    event = DisasterEvent(
        "test:flood-1", Disaster.FLOOD, "Test City", country, NOW, source
    )
    provider = NewFloodProvider(event)
    registration = ProviderRegistration(
        "Testland flood authority",
        provider,
        ProviderCapabilities(
            frozenset({ProviderRole.EVENT_DISCOVERY}),
            frozenset({Disaster.FLOOD}),
            frozenset({"TST"}),
        ),
        source_id="testland-floods",
        event_provider=provider,
    )
    registry = ProviderRegistry((registration,))
    descriptor = SourceDescriptor(
        "testland-floods",
        "Test authority",
        "Test floods",
        "Testland",
        "national_authority",
        (SourceInformationRole.EVENT_DISCOVERY,),
        (Disaster.FLOOD,),
        ("TST",),
        ("en",),
        "test",
        False,
        True,
        "unknown",
        "Attribute to test authority.",
        (),
        ("find_disaster_event",),
        "Testland flood authority",
        "implemented",
        (GeographicScope.COUNTRY,),
    )
    query = DisasterQuery(Disaster.FLOOD, country, "recent", ("latest",))
    task = ValidatedDisasterTask(
        "Latest flood in Testland",
        TaskKind.INVESTIGATION,
        True,
        Disaster.FLOOD,
        country,
        information_needs=(InformationNeed.EVENT_OVERVIEW,),
        output_modalities=(OutputModality.TEXT,),
        query=query,
    )
    tools = build_disaster_tool_registry(
        DisasterToolDependencies(
            registry,
            FakeCatalog(descriptor),
            provider,
            EmptySituationProvider(),
            default_event_policy_registry(),
            EvidenceReconciler(),
            DisasterReportRenderer(),
            lambda: NOW,
        )
    )
    plan = InvestigationPlan(
        "p",
        "discover",
        (
            PlanStep("sources", "list_sources_for_task", (), "list"),
            PlanStep("event", "find_disaster_event", (), "find", ("sources",)),
        ),
    )
    state = AgentExecutionState(task, plan)

    await execute_plan(state, tools)

    assert state.workspace.source_selection is not None
    assert state.workspace.source_selection.configured_source_ids == (
        "testland-floods",
    )
    assert state.workspace.selected_event == event
    assert provider.calls == 1
    retrieve = tools.resolve("retrieve_situation_evidence")
    assert retrieve.description.supported_information_roles == ()
    assert retrieve.supported_information_roles(state) == ()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_runtime_uses_deterministic_plan_when_agent_model_is_unavailable() -> (
    None
):
    catalog = StaticCountryCatalog()
    japan = catalog.get_by_alpha3("JPN")
    assert japan is not None
    source = SourceReference(
        "global-catalog-rolling-earthquakes",
        "Global Catalog",
        "Event",
        "https://example.test/event",
        NOW,
        NOW,
        NOW,
    )
    event = DisasterEvent(
        "global-catalog:fallback",
        Disaster.EARTHQUAKE,
        "Ishikawa, Japan",
        japan,
        NOW,
        source,
    )
    provider = NewFloodProvider(event)
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "Global Catalog rolling earthquake",
                provider,
                ProviderCapabilities(
                    frozenset({ProviderRole.EVENT_DISCOVERY}),
                    frozenset({Disaster.EARTHQUAKE}),
                    frozenset({"JPN"}),
                ),
                source_id="global-catalog-rolling-earthquakes",
                event_provider=provider,
            ),
        )
    )
    tools = build_disaster_tool_registry(
        DisasterToolDependencies(
            registry,
            StaticSourceCatalog(),
            provider,
            EmptySituationProvider(),
            default_event_policy_registry(),
            EvidenceReconciler(),
            DisasterReportRenderer(),
            lambda: NOW,
        )
    )
    runtime = DisasterAgentRuntime(
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
        tool_registry=tools,
        agent_model=None,
    )

    state = await runtime.run("Give me the latest earthquake information in Japan.")

    assert state.plan == default_investigation_plan(state.task)
    assert state.workspace.selected_event == event
    assert state.workspace.report is not None
    assert len(state.workspace.hypotheses) == 1
    assert state.workspace.hypotheses[0].truth_status == "inferred"
    assert state.workspace.incident_priority is not None
    assert state.workspace.incident_priority.evidence_state_version == (
        state.workspace.evidence_state.state_version
    )
    assert state.workspace.triage_decision is not None
    assert state.workspace.triage_decision.assessment_id == (
        state.workspace.incident_priority.assessment_id
    )
    assert (
        state.workspace.hypotheses[0].proposition not in state.workspace.report.message
    )
    assert state.model_call_count == 0

    class ReplanAgent:
        async def interpret(self, question):
            return DisasterTaskDraft(
                True,
                True,
                ("earthquake",),
                ("Japan",),
                information_needs=("event_overview",),
                output_modalities=("text",),
            )

        async def propose_plan(self, task, tool_descriptions):
            return default_investigation_plan(task)

        async def review_progress(self, task, completed_steps):
            return AgentReview(ReviewDecision.REPLAN, "Try an alternative")

    reviewed = await DisasterAgentRuntime(
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
        tool_registry=tools,
        agent_model=ReplanAgent(),
    ).run("Give me the latest earthquake information in Japan.")

    assert reviewed.replan_count == 1
    assert reviewed.model_call_count == 2
    assert any("no distinct" in warning.lower() for warning in reviewed.warnings)


def test_packaged_source_catalog_has_only_implemented_non_visual_sources() -> None:
    catalog = StaticSourceCatalog()

    assert {item.source_id for item in catalog.sources()} == {
        "cems-gfm-floods",
        "gdacs-tropical-cyclones",
        "nasa-coolr-landslides",
        "nasa-eonet-wildfires",
        "reliefweb-situation-reports",
        "smithsonian-usgs-volcanic-activity",
        "usgs-earthquakes",
    }
    assert all(
        item.implementation_status == "implemented" for item in catalog.sources()
    )
    assert all(
        SourceInformationRole.IMAGERY not in item.information_roles
        and SourceInformationRole.MAP_LAYERS not in item.information_roles
        for item in catalog.sources()
    )


def test_provider_source_consistency_detects_missing_metadata() -> None:
    country = Country("TST", "Testland", (), GeographicArea(0, 1, 0, 1), "UTC")
    event = DisasterEvent(
        "test:event",
        Disaster.FLOOD,
        "Testland",
        country,
        NOW,
        SourceReference(
            "not-in-catalog",
            "Test",
            "Event",
            "https://example.test/event",
            NOW,
            NOW,
            NOW,
        ),
    )
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "Missing source",
                NewFloodProvider(event),
                ProviderCapabilities(
                    frozenset({ProviderRole.EVENT_DISCOVERY}),
                    frozenset({Disaster.FLOOD}),
                    frozenset({"TST"}),
                ),
                source_id="not-in-catalog",
                event_provider=NewFloodProvider(event),
            ),
        )
    )

    with pytest.raises(ValueError, match="no matching source descriptor"):
        validate_provider_source_consistency(registry, StaticSourceCatalog())
