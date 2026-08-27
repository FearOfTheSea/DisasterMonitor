"""Specialist coordination and grounded answer-composition tooling."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InformationNeed,
    SourceInformationRole,
)
from disaster_monitor.application.agent.tools import ToolDescription
from disaster_monitor.application.disaster import (
    DisasterReport,
    ReportSection,
    SelectedEventSummary,
)
from disaster_monitor.application.services.collaborative_investigation import (
    render_collaborative_investigation,
)
from disaster_monitor.application.services.coordination_supervision import (
    CoordinationSupervisor,
    render_coordination_supervision,
)
from disaster_monitor.application.services.decision_autonomy import (
    render_decision_execution,
)
from disaster_monitor.application.services.decision_support import (
    render_decision_support,
)
from disaster_monitor.application.services.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.services.specialist_executor import (
    SpecialistExecutor,
)
from disaster_monitor.domain.coordination import SpecialistFinding


@dataclass(frozen=True, slots=True)
class CoordinationToolDependencies:
    renderer: DisasterReportRenderer
    coordination_supervisor: CoordinationSupervisor
    clock: Callable[[], datetime]
    specialist_executor: SpecialistExecutor | None = None


class _CoordinationTool:
    def __init__(self, dependencies: CoordinationToolDependencies) -> None:
        self.dependencies = dependencies

    def now(self) -> datetime:
        value = self.dependencies.clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ComposeDisasterAnswerTool(_CoordinationTool):
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
            injected_findings: tuple[SpecialistFinding, ...] = ()
            if self.dependencies.specialist_executor is not None:
                specialist_result = await self.dependencies.specialist_executor.execute(
                    state.workspace.evidence_state,
                    state.workspace.specialist_handoffs,
                    decision_support=state.workspace.decision_support,
                    memory_context=state.workspace.memory_context,
                    request_model_calls=state.specialist_model_call_count,
                )
                state.specialist_model_call_count += specialist_result.model_call_count
                state.specialist_fallback_reason = specialist_result.fallback_reason
                state.specialist_provenance_validation_failures += (
                    specialist_result.provenance_validation_failures
                )
                state.specialist_latency_ms += specialist_result.latency_ms
                injected_findings = specialist_result.findings
            supervision = self.dependencies.coordination_supervisor.run(
                state.workspace.evidence_state,
                state.workspace.specialist_handoffs,
                decision_support=state.workspace.decision_support,
                multimodal_state=state.workspace.multimodal_state,
                injected_findings=injected_findings,
            )
            state.workspace.coordination_supervision = supervision
            state.workspace.collaborative_investigation = supervision.collaboration
        state.workspace.report = compose_report(
            state, self.dependencies.renderer, self.now()
        )
        return "Composed a grounded answer from the available normalized evidence."


def compose_report(
    state: AgentExecutionState, renderer: DisasterReportRenderer, retrieved_at: datetime
) -> DisasterReport:
    task = state.task
    packet = state.workspace.evidence_packet
    if packet is None:
        coverage_unavailable = bool(state.capability_gaps)
        if state.workspace.event_batch is not None:
            coverage_unavailable = False
        if coverage_unavailable and task.disaster and task.country:
            detail = (
                f"I recognized a request for current {task.disaster.value} information "
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
                f"{task.disaster.value if task.disaster else 'disaster'} event in "
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
                f"{fact.source.publisher} â€” {fact.source.title} "
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
            event_id=packet.event.event_id,
            disaster=packet.event.disaster,
            location=packet.event.location,
            event_time=packet.event.event_time,
            geometry=packet.event.geometry,
            measurements=packet.event.measurements,
            source=packet.event.source,
            provider_ids=packet.event.provider_ids,
            geography_status=packet.event.geography_status,
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


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
