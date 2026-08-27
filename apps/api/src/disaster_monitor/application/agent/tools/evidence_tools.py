"""Evidence reconciliation, persistence, memory, and triage tooling."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    SourceInformationRole,
)
from disaster_monitor.application.agent.tools import ToolDescription
from disaster_monitor.application.agent.tools.decision_tools import DecisionTools
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.hypothesis_reasoning import (
    HypothesisGenerator,
)
from disaster_monitor.application.services.incident_priority import (
    IncidentPriorityRanker,
)
from disaster_monitor.application.services.memory_recall import (
    MemoryRecallRequest,
    MemoryRecallService,
)
from disaster_monitor.application.services.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.services.triage_autonomy import TriageAutonomyPolicy

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvidenceToolDependencies:
    evidence_reconciler: EvidenceReconciler
    hypothesis_generator: HypothesisGenerator
    priority_ranker: IncidentPriorityRanker
    triage_policy: TriageAutonomyPolicy
    decision_tools: DecisionTools
    clock: Callable[[], datetime]
    operational_evidence: OperationalEvidenceRecorder | None = None
    memory_recall: MemoryRecallService | None = None


class _EvidenceTool:
    def __init__(self, dependencies: EvidenceToolDependencies) -> None:
        self.dependencies = dependencies

    def now(self) -> datetime:
        value = self.dependencies.clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ReconcileDisasterEvidenceTool(_EvidenceTool):
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
            if (
                self.dependencies.memory_recall is not None
                and state.conversation_id is not None
            ):
                try:
                    memory_recall = self.dependencies.memory_recall
                    state.workspace.memory_context = await memory_recall.recall(
                        MemoryRecallRequest(
                            conversation_id=state.conversation_id,
                            physical_event_id=(
                                packet.world_state.physical_event.physical_event_id
                            ),
                            disaster_identifier=(
                                packet.world_state.physical_event.event.disaster.value
                            ),
                            country_code=(
                                packet.world_state.physical_event.event.country.alpha3_code
                            ),
                            now=self.now(),
                        )
                    )
                except Exception:
                    logger.exception("Typed historical-memory recall failed")
            self.dependencies.decision_tools.apply(state, packet.world_state)
        state.workspace.evidence_packet = packet
        return (
            f"Reconciled {len(packet.facts)} facts from {len(packet.sources)} sources."
        )
