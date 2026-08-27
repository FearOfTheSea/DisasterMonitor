"""Compatibility facade and composition for bounded disaster-agent tools."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from disaster_monitor.application.agent.tools import (
    AgentTool,
    ToolDescription,
    ToolRegistry,
    execute_plan,
)
from disaster_monitor.application.agent.tools.coordination_tools import (
    ComposeDisasterAnswerTool,
    CoordinationToolDependencies,
    compose_report,
)
from disaster_monitor.application.agent.tools.decision_tools import (
    DecisionToolDependencies,
    DecisionTools,
)
from disaster_monitor.application.agent.tools.evidence_tools import (
    EvidenceToolDependencies,
    ReconcileDisasterEvidenceTool,
)
from disaster_monitor.application.agent.tools.source_tools import (
    FindDisasterEventTool,
    ListSourcesForTaskTool,
    RetrieveSituationEvidenceTool,
    SourceToolDependencies,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.application.services.coordination_handoffs import (
    CoordinationHandoffPlanner,
)
from disaster_monitor.application.services.coordination_supervision import (
    CoordinationSupervisor,
)
from disaster_monitor.application.services.decision_autonomy import (
    DecisionAutonomyController,
)
from disaster_monitor.application.services.decision_support import (
    DecisionOptionGenerator,
)
from disaster_monitor.application.services.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.services.event_resolution import EventPolicyRegistry
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.hypothesis_reasoning import (
    HypothesisGenerator,
)
from disaster_monitor.application.services.incident_priority import (
    IncidentPriorityRanker,
)
from disaster_monitor.application.services.memory_recall import MemoryRecallService
from disaster_monitor.application.services.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.services.provider_registry import ProviderRegistry
from disaster_monitor.application.services.specialist_executor import (
    SpecialistExecutor,
)
from disaster_monitor.application.services.triage_autonomy import TriageAutonomyPolicy


@dataclass(frozen=True, slots=True)
class DisasterToolDependencies:
    """Compatibility aggregate accepted only at the tool composition boundary."""

    provider_registry: ProviderRegistry
    source_catalog: SourceCatalog
    event_provider: DisasterEventProvider
    situation_provider: SituationReportProvider
    event_policies: EventPolicyRegistry
    evidence_reconciler: EvidenceReconciler
    renderer: DisasterReportRenderer
    clock: Callable[[], datetime]
    hypothesis_generator: HypothesisGenerator = field(
        default_factory=HypothesisGenerator
    )
    priority_ranker: IncidentPriorityRanker = field(
        default_factory=IncidentPriorityRanker
    )
    triage_policy: TriageAutonomyPolicy = field(default_factory=TriageAutonomyPolicy)
    decision_option_generator: DecisionOptionGenerator = field(
        default_factory=DecisionOptionGenerator
    )
    decision_autonomy: DecisionAutonomyController = field(
        default_factory=DecisionAutonomyController
    )
    handoff_planner: CoordinationHandoffPlanner = field(
        default_factory=CoordinationHandoffPlanner
    )
    coordination_supervisor: CoordinationSupervisor = field(
        default_factory=CoordinationSupervisor
    )
    operational_evidence: OperationalEvidenceRecorder | None = None
    specialist_executor: SpecialistExecutor | None = None
    memory_recall: MemoryRecallService | None = None


def build_disaster_tool_registry(
    dependencies: DisasterToolDependencies,
    additional_tools: Iterable[AgentTool] = (),
) -> ToolRegistry:
    """Compose capability-specific tools from narrow dependency bundles."""
    source = SourceToolDependencies(
        provider_registry=dependencies.provider_registry,
        source_catalog=dependencies.source_catalog,
        event_provider=dependencies.event_provider,
        situation_provider=dependencies.situation_provider,
        event_policies=dependencies.event_policies,
        clock=dependencies.clock,
    )
    decision = DecisionTools(
        DecisionToolDependencies(
            option_generator=dependencies.decision_option_generator,
            autonomy=dependencies.decision_autonomy,
            handoff_planner=dependencies.handoff_planner,
        )
    )
    evidence = EvidenceToolDependencies(
        evidence_reconciler=dependencies.evidence_reconciler,
        hypothesis_generator=dependencies.hypothesis_generator,
        priority_ranker=dependencies.priority_ranker,
        triage_policy=dependencies.triage_policy,
        decision_tools=decision,
        clock=dependencies.clock,
        operational_evidence=dependencies.operational_evidence,
        memory_recall=dependencies.memory_recall,
    )
    coordination = CoordinationToolDependencies(
        renderer=dependencies.renderer,
        coordination_supervisor=dependencies.coordination_supervisor,
        clock=dependencies.clock,
        specialist_executor=dependencies.specialist_executor,
    )
    return ToolRegistry(
        (
            ListSourcesForTaskTool(source),
            FindDisasterEventTool(source),
            RetrieveSituationEvidenceTool(source),
            ReconcileDisasterEvidenceTool(evidence),
            ComposeDisasterAnswerTool(coordination),
            *tuple(additional_tools),
        )
    )


__all__ = [
    "AgentTool",
    "ComposeDisasterAnswerTool",
    "DisasterToolDependencies",
    "FindDisasterEventTool",
    "ListSourcesForTaskTool",
    "ReconcileDisasterEvidenceTool",
    "RetrieveSituationEvidenceTool",
    "ToolDescription",
    "ToolRegistry",
    "build_disaster_tool_registry",
    "compose_report",
    "execute_plan",
]
