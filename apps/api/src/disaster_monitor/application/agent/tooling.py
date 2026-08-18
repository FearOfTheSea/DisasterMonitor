"""Allowlisted typed tools exposing the existing trusted disaster workflow."""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InformationNeed,
    InvestigationAction,
    SourceInformationRole,
    SourceSelectionSummary,
)
from disaster_monitor.application.disaster import (
    DisasterReport,
    ProviderBatch,
    ReportSection,
    SelectedEventSummary,
)
from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.ports.source_catalog import SourceCatalog
from disaster_monitor.application.services.collaborative_investigation import (
    render_collaborative_investigation,
)
from disaster_monitor.application.services.coordination_handoffs import (
    CoordinationHandoffPlanner,
)
from disaster_monitor.application.services.coordination_supervision import (
    CoordinationSupervisor,
    render_coordination_supervision,
)
from disaster_monitor.application.services.decision_autonomy import (
    DecisionAutonomyController,
    render_decision_execution,
)
from disaster_monitor.application.services.decision_support import (
    DecisionOptionGenerator,
    render_decision_support,
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
from disaster_monitor.application.services.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.triage_autonomy import TriageAutonomyPolicy

MAX_TOOL_CALLS = 12
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolDescription:
    name: str
    description: str
    required_state: tuple[str, ...]
    accepted_arguments: tuple[str, ...]
    produced_artifacts: tuple[str, ...]
    supported_information_roles: tuple[str, ...]
    performs_live_io: bool

    def planning_text(self) -> str:
        return f"{self.name}: {self.description}"


class AgentTool(Protocol):
    description: ToolDescription

    async def execute(self, state: AgentExecutionState) -> str: ...


class ToolRegistry:
    """Immutable allowlist of explicitly constructed agent tools."""

    def __init__(self, tools: Iterable[AgentTool]) -> None:
        resolved = tuple(tools)
        names = [tool.description.name for tool in resolved]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate agent tool name.")
        self._tools = {tool.description.name: tool for tool in resolved}
        self._descriptions = tuple(tool.description for tool in resolved)

    @property
    def descriptions(self) -> tuple[ToolDescription, ...]:
        return self._descriptions

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def resolve(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ValueError(f"Unknown agent tool: {name}") from error


@dataclass(frozen=True, slots=True)
class DisasterToolDependencies:
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


def build_disaster_tool_registry(
    dependencies: DisasterToolDependencies,
    additional_tools: Iterable[AgentTool] = (),
) -> ToolRegistry:
    return ToolRegistry(
        (
            ListSourcesForTaskTool(dependencies),
            FindDisasterEventTool(dependencies),
            RetrieveSituationEvidenceTool(dependencies),
            ReconcileDisasterEvidenceTool(dependencies),
            ComposeDisasterAnswerTool(dependencies),
            *tuple(additional_tools),
        )
    )


class _BaseTool:
    def __init__(self, dependencies: DisasterToolDependencies) -> None:
        self.dependencies = dependencies

    def now(self) -> datetime:
        value = self.dependencies.clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ListSourcesForTaskTool(_BaseTool):
    description = ToolDescription(
        "list_sources_for_task",
        "Match maintained source intelligence to the validated hazard, country, "
        "and roles.",
        ("validated_task",),
        (),
        ("source_selection",),
        tuple(role.value for role in SourceInformationRole),
        False,
    )

    async def execute(self, state: AgentExecutionState) -> str:
        task = state.task
        if task.query is None or task.hazard is None or task.country is None:
            raise ValueError("Source selection requires a canonical disaster query.")
        configured: list[str] = []
        unconfigured: list[str] = []
        for registration in self.dependencies.provider_registry.registrations:
            if not registration.source_id:
                continue
            if any(
                registration.capabilities.supports(task.query, role)
                for role in ProviderRole
            ):
                (configured if registration.configured else unconfigured).append(
                    registration.source_id
                )
        requested_roles = _requested_source_roles(task.information_needs)
        catalog_matches = {
            source.source_id
            for source in self.dependencies.source_catalog.sources()
            if task.hazard in source.supported_hazards
            and (
                source.country_codes is None
                or task.country.alpha3_code in source.country_codes
            )
        }
        unsupported_roles = tuple(
            role.value
            for role in requested_roles
            if not any(
                role in source.information_roles
                for source in self.dependencies.source_catalog.sources()
                if source.source_id in catalog_matches
            )
        )
        satisfied_by_admitted_assets = (
            {
                SourceInformationRole.IMAGERY.value,
                SourceInformationRole.MAP_LAYERS.value,
            }
            if state.workspace.multimodal_assets
            else set()
        )
        unsupported = tuple(
            role
            for role in unsupported_roles
            if role not in satisfied_by_admitted_assets
        )
        executable_ids = set(configured) | set(unconfigured)
        known_not_executable = tuple(sorted(catalog_matches - executable_ids))
        supplementary = tuple(
            source.source_id
            for source in self.dependencies.source_catalog.sources()
            if source.source_id in catalog_matches
            and SourceInformationRole.HUMANITARIAN_REPORTING in source.information_roles
        )
        gaps = []
        event_selection = self.dependencies.provider_registry.select(
            task.query, ProviderRole.EVENT_DISCOVERY
        )
        if not event_selection.registrations:
            gaps.append("No event-verification source is executable for this task.")
        for role in unsupported:
            gaps.append(f"No maintained executable source supports role {role}.")
        state.workspace.source_selection = SourceSelectionSummary(
            configured_source_ids=tuple(configured),
            unconfigured_source_ids=tuple(unconfigured),
            known_not_executable_source_ids=known_not_executable,
            supplementary_source_ids=supplementary,
            unsupported_roles=unsupported,
            coverage_gaps=tuple(gaps),
        )
        state.workspace.source_ids.extend(configured)
        state.capability_gaps.extend(gaps)
        return (
            f"Selected {len(configured)} configured source registrations; "
            f"{len(unconfigured)} suitable registrations require configuration."
        )


class FindDisasterEventTool(_BaseTool):
    description = ToolDescription(
        "find_disaster_event",
        "Query capability-selected event providers and resolve one physical event.",
        ("validated_task", "source_selection"),
        (),
        ("event_batch", "selected_event", "alternatives"),
        (SourceInformationRole.EVENT_DISCOVERY.value,),
        True,
    )

    async def execute(self, state: AgentExecutionState) -> str:
        task = state.task
        if task.query is None:
            raise ValueError("Event discovery requires a canonical disaster query.")
        selection = self.dependencies.provider_registry.select(
            task.query, ProviderRole.EVENT_DISCOVERY
        )
        if not selection.registrations:
            state.capability_gaps.append(
                "No event-discovery provider supports this hazard and country."
            )
            return "No event-discovery provider is available for the validated task."
        try:
            batch = await self.dependencies.event_provider.find_recent_events(
                task.query, now=self.now()
            )
            state.workspace.event_batch = _as_batch(batch)
        except Exception:
            state.workspace.event_batch = ProviderBatch()
            state.warnings.append(
                f"A {task.query.hazard.value} event source could not be reached or "
                "returned invalid data."
            )
        state.warnings.extend(
            issue.message for issue in state.workspace.event_batch.issues
        )
        policy = self.dependencies.event_policies.for_hazard(task.query.hazard)
        resolution = policy.resolve(
            state.workspace.event_batch.records,
            task.query,
            now=self.now(),
        )
        state.workspace.physical_events = resolution.physical_events
        state.workspace.selected_physical_event = resolution.selected_physical_event
        state.workspace.selected_event = resolution.selected
        state.workspace.alternatives = resolution.alternatives
        if resolution.selected is None:
            return "No matching event could be verified from the selected sources."
        return f"Selected the source-backed event {resolution.selected.event_id}."


class RetrieveSituationEvidenceTool(_BaseTool):
    description = ToolDescription(
        "retrieve_situation_evidence",
        "Retrieve normalized event-correlated official and supplementary reports.",
        ("selected_event",),
        (),
        ("situation_reports", "provider_issues"),
        (),
        True,
    )

    def supported_information_roles(
        self, state: AgentExecutionState
    ) -> tuple[str, ...]:
        query = state.task.query
        if query is None:
            return ()
        selection = self.dependencies.provider_registry.select(
            query, ProviderRole.SITUATION_EVIDENCE
        )
        source_ids = {
            registration.source_id
            for registration in selection.registrations
            if registration.source_id
        }
        roles = {
            role.value
            for source in self.dependencies.source_catalog.sources()
            if source.source_id in source_ids
            for role in source.information_roles
        }
        requested = set(_requested_source_roles(state.task.information_needs))
        return tuple(sorted(roles & requested))

    async def execute(self, state: AgentExecutionState) -> str:
        event = state.workspace.selected_event
        query = state.task.query
        if event is None or query is None:
            raise ValueError("Situation evidence requires a selected event.")
        selection = self.dependencies.provider_registry.select(
            query, ProviderRole.SITUATION_EVIDENCE, event=event
        )
        state.warnings.extend(
            f"{name} is unavailable because required configuration is missing."
            for name in selection.unavailable_configuration
        )
        if not selection.registrations:
            state.workspace.situation_batch = ProviderBatch()
            state.capability_gaps.append(
                "No configured situation-evidence provider supports the selected event."
            )
            return (
                "No situation-evidence provider is executable for the selected event."
            )
        try:
            batch = await self.dependencies.situation_provider.get_situation_reports(
                event, query, now=self.now()
            )
            state.workspace.situation_batch = _as_batch(batch)
        except Exception:
            state.workspace.situation_batch = ProviderBatch()
            state.warnings.append(
                "The situation-report source could not be reached or returned "
                "invalid data."
            )
        state.warnings.extend(
            issue.message for issue in state.workspace.situation_batch.issues
        )
        return (
            f"Retrieved {len(state.workspace.situation_batch.records)} "
            "situation reports."
        )


class ReconcileDisasterEvidenceTool(_BaseTool):
    description = ToolDescription(
        "reconcile_disaster_evidence",
        "Reconcile normalized reports while preserving source conflicts and "
        "missing evidence.",
        ("selected_event", "situation_reports"),
        (),
        ("evidence_packet",),
        tuple(role.value for role in SourceInformationRole),
        False,
    )

    async def execute(self, state: AgentExecutionState) -> str:
        event = state.workspace.selected_event
        query = state.task.query
        reports = state.workspace.situation_batch
        if event is None or query is None or reports is None:
            raise ValueError(
                "Evidence reconciliation requires event and situation results."
            )
        packet = self.dependencies.evidence_reconciler.build(
            query,
            event,
            reports.records,
            warnings=tuple(dict.fromkeys(state.warnings)),
            retrieved_at=self.now(),
            physical_event=state.workspace.selected_physical_event,
        )
        state.workspace.evidence_state = packet.world_state
        if packet.world_state is not None:
            if self.dependencies.operational_evidence is not None:
                try:
                    persistence = await self.dependencies.operational_evidence.record(
                        packet.world_state
                    )
                except Exception:
                    logger.exception("Durable evidence persistence failed")
                    state.warnings.append(
                        "Durable evidence persistence failed; this response remains "
                        "request-scoped and is not presented as stored history."
                    )
                else:
                    if not persistence.persisted:
                        state.warnings.append(
                            "Durable evidence history was not written because one or "
                            "more facts lacked an immutable source snapshot."
                        )
            state.workspace.hypotheses = (
                self.dependencies.hypothesis_generator.generate(packet.world_state)
            )
            state.workspace.incident_priority = (
                self.dependencies.priority_ranker.assess(packet.world_state)
            )
            state.workspace.triage_decision = self.dependencies.triage_policy.decide(
                state.workspace.incident_priority
            )
            try:
                evidence_handoff = self.dependencies.handoff_planner.for_evidence_state(
                    packet.world_state
                )
                state.workspace.specialist_handoffs = (evidence_handoff,)
            except ValueError:
                state.capability_gaps.append(
                    "Typed specialist handoff failed its ownership or provenance "
                    "gate; the single-supervisor path remains active."
                )
            if InformationNeed.DECISION_SUPPORT in state.task.information_needs:
                try:
                    decision_support = (
                        self.dependencies.decision_option_generator.generate(
                            packet.world_state,
                            state.workspace.hypotheses,
                            state.workspace.incident_priority,
                            state.workspace.triage_decision,
                        )
                    )
                    state.workspace.decision_support = decision_support
                    state.workspace.decision_outcome = (
                        self.dependencies.decision_autonomy.execute(decision_support)
                    )
                except ValueError:
                    state.capability_gaps.append(
                        "Decision support failed its evidence-lineage safety gate; "
                        "the deterministic report remains available."
                    )
                else:
                    try:
                        decision_handoff = (
                            self.dependencies.handoff_planner.for_decision_support(
                                decision_support
                            )
                        )
                        state.workspace.specialist_handoffs = (
                            *state.workspace.specialist_handoffs,
                            decision_handoff,
                        )
                    except ValueError:
                        state.capability_gaps.append(
                            "Typed specialist handoff failed its ownership or "
                            "provenance gate; the single-supervisor path remains "
                            "active."
                        )
        state.workspace.evidence_packet = packet
        return (
            f"Reconciled {len(packet.facts)} facts from {len(packet.sources)} sources."
        )


class ComposeDisasterAnswerTool(_BaseTool):
    description = ToolDescription(
        "compose_disaster_answer",
        "Compose a deterministic focused or full answer from normalized evidence only.",
        ("evidence_packet_or_capability_gap",),
        (),
        ("disaster_report",),
        tuple(role.value for role in SourceInformationRole),
        False,
    )

    async def execute(self, state: AgentExecutionState) -> str:
        if state.workspace.evidence_state is not None:
            supervision = self.dependencies.coordination_supervisor.run(
                state.workspace.evidence_state,
                state.workspace.specialist_handoffs,
                decision_support=state.workspace.decision_support,
                multimodal_state=state.workspace.multimodal_state,
            )
            state.workspace.coordination_supervision = supervision
            state.workspace.collaborative_investigation = supervision.collaboration
        state.workspace.report = compose_report(
            state, self.dependencies.renderer, self.now()
        )
        return "Composed a grounded answer from the available normalized evidence."


async def execute_plan(state: AgentExecutionState, registry: ToolRegistry) -> None:
    """Execute a validated plan with strict sequencing and call budgets."""
    completed = set(state.completed_steps)
    state.pending_steps = [step.step_id for step in state.plan.steps]
    for step in state.plan.steps:
        if state.tool_call_count >= MAX_TOOL_CALLS:
            raise RuntimeError("The agent tool-call budget was exhausted.")
        if any(dependency not in completed for dependency in step.dependencies):
            raise ValueError("An agent tool prerequisite was not completed.")
        tool = registry.resolve(step.tool_name)
        if state.workspace.selected_event is None and step.tool_name in {
            "retrieve_situation_evidence",
            "reconcile_disaster_evidence",
            "analyze_multimodal_assets",
            "build_common_operational_picture",
        }:
            action = "Skipped because no selected event was available."
        else:
            action = await tool.execute(state)
        state.tool_call_count += 1
        state.completed_steps.append(step.step_id)
        completed.add(step.step_id)
        state.pending_steps.remove(step.step_id)
        state.actions.append(InvestigationAction(step.step_id, action))


def compose_report(
    state: AgentExecutionState, renderer: DisasterReportRenderer, retrieved_at: datetime
) -> DisasterReport:
    task = state.task
    packet = state.workspace.evidence_packet
    if packet is None:
        coverage_unavailable = bool(state.capability_gaps)
        if state.workspace.event_batch is not None:
            coverage_unavailable = False
        if coverage_unavailable and task.hazard and task.country:
            detail = (
                f"I recognized a request for current {task.hazard.value} information "
                f"in {task.country.canonical_name}, but no configured source-backed "
                "event provider supports this combination. No live factual claim is "
                "being made."
            )
        else:
            country_name = (
                task.country.canonical_name if task.country else "the requested area"
            )
            detail = task.detail or (
                f"I could not verify a matching recent "
                f"{task.hazard.value if task.hazard else 'disaster'} event in "
                f"{country_name} from the configured sources."
            )
        section = ReportSection("Situation summary", detail)
        return DisasterReport(
            message=f"## Situation summary\n{detail}",
            response_type=(
                "current_disaster_coverage_unavailable"
                if coverage_unavailable
                else "current_disaster_verification_failed"
            ),
            selected_event=None,
            retrieval_time=retrieved_at,
            sources=(),
            warnings=tuple(dict.fromkeys(state.warnings)),
            sections=(section,),
            partial=True,
        )
    focused = _focused_category(task.information_needs)
    if focused is None:
        message, sections = renderer.render(packet)
    else:
        facts = tuple(fact for fact in packet.facts if fact.category == focused)
        event = packet.event
        event_detail = (
            f"The selected event is {event.event_id} at {event.location}, "
            f"{event.event_time.astimezone(UTC).isoformat().replace('+00:00', 'Z')}."
        )
        if facts:
            fact_lines = "\n".join(
                f"- {fact.label}: {fact.value} ({fact.status.value}). Source: "
                f"{fact.source.publisher} — {fact.source.title} "
                f"({fact.source.canonical_url}); fresh as of "
                f"{_utc_text(fact.source.effective_at)}."
                for fact in facts
            )
        else:
            fact_lines = (
                f"No reliable {focused.replace('_', ' ')} evidence was found in the "
                "retrieved reports; this is not evidence of a zero value."
            )
        conflicts = (
            " ".join(packet.conflicts)
            if packet.conflicts
            else "No conflicting retrieved figures were identified."
        )
        sections = (
            ReportSection("Focused answer", fact_lines),
            ReportSection("Event details", event_detail),
            ReportSection("Conflicts and uncertainty", conflicts),
            ReportSection(
                "Report freshness",
                f"Evidence retrieved at {_utc_text(retrieved_at)}.",
            ),
        )
        message = "\n\n".join(f"## {item.title}\n{item.content}" for item in sections)
    if state.workspace.decision_support is not None:
        decision_section = ReportSection(
            "Decision support",
            "\n".join(
                (
                    render_decision_support(state.workspace.decision_support),
                    *(
                        (render_decision_execution(state.workspace.decision_outcome),)
                        if state.workspace.decision_outcome is not None
                        else ()
                    ),
                )
            ),
        )
        sections = (*sections, decision_section)
        message = f"{message}\n\n## Decision support\n{decision_section.content}"
    collaboration = state.workspace.collaborative_investigation
    if collaboration is not None and collaboration.findings:
        coordination_section = ReportSection(
            "Specialist coordination",
            "\n".join(
                (
                    render_collaborative_investigation(collaboration),
                    *(
                        (
                            render_coordination_supervision(
                                state.workspace.coordination_supervision
                            ),
                        )
                        if state.workspace.coordination_supervision is not None
                        else ()
                    ),
                )
            ),
        )
        sections = (*sections, coordination_section)
        message = (
            f"{message}\n\n## Specialist coordination\n{coordination_section.content}"
        )
    gaps = tuple(dict.fromkeys((*state.plan.capability_gaps, *state.capability_gaps)))
    if gaps:
        gap_section = ReportSection("Capability gaps", " ".join(gaps))
        sections = (*sections, gap_section)
        message = f"{message}\n\n## Capability gaps\n{gap_section.content}"
    return DisasterReport(
        message=message,
        response_type="current_disaster",
        selected_event=SelectedEventSummary(
            packet.event.event_id,
            packet.event.hazard,
            packet.event.location,
            packet.event.event_time,
            packet.event.latitude,
            packet.event.longitude,
            packet.event.magnitude,
            packet.event.intensity,
            packet.event.depth_km,
            packet.event.source,
            packet.event.provider_ids,
        ),
        retrieval_time=retrieved_at,
        sources=packet.sources,
        warnings=tuple(dict.fromkeys((*packet.warnings, *gaps))),
        sections=tuple(sections),
        partial=packet.partial or bool(gaps),
    )


def _focused_category(needs: tuple[InformationNeed, ...]) -> str | None:
    mapping = {
        InformationNeed.FATALITIES: "fatalities",
        InformationNeed.INJURIES: "injuries",
        InformationNeed.MISSING_PERSONS: "missing",
        InformationNeed.EVACUATIONS: "evacuations",
    }
    focused = [mapping[item] for item in needs if item in mapping]
    return focused[0] if len(focused) == 1 else None


def _requested_source_roles(
    needs: tuple[InformationNeed, ...],
) -> tuple[SourceInformationRole, ...]:
    roles = [SourceInformationRole.EVENT_DISCOVERY]
    mapping = {
        InformationNeed.FATALITIES: SourceInformationRole.CASUALTY_REPORTING,
        InformationNeed.INJURIES: SourceInformationRole.CASUALTY_REPORTING,
        InformationNeed.MISSING_PERSONS: SourceInformationRole.CASUALTY_REPORTING,
        InformationNeed.PHYSICAL_DAMAGE: SourceInformationRole.PHYSICAL_DAMAGE,
        InformationNeed.INFRASTRUCTURE_DISRUPTION: (
            SourceInformationRole.INFRASTRUCTURE_STATUS
        ),
        InformationNeed.WARNINGS: SourceInformationRole.OFFICIAL_WARNING,
        InformationNeed.EMERGENCY_RESPONSE: SourceInformationRole.EMERGENCY_RESPONSE,
        InformationNeed.IMAGES: SourceInformationRole.IMAGERY,
        InformationNeed.MAP_VISUALIZATION: SourceInformationRole.MAP_LAYERS,
    }
    roles.extend(mapping[item] for item in needs if item in mapping)
    return tuple(dict.fromkeys(roles))


def _as_batch[T](value: ProviderBatch[T] | tuple[T, ...]) -> ProviderBatch[T]:
    return value if isinstance(value, ProviderBatch) else ProviderBatch(tuple(value))


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
