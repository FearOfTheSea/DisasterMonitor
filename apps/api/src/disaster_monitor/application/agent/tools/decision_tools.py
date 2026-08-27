"""Decision-support and typed handoff processing for reconciled evidence."""

from dataclasses import dataclass

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InformationNeed,
)
from disaster_monitor.application.services.coordination_handoffs import (
    CoordinationHandoffPlanner,
)
from disaster_monitor.application.services.decision_autonomy import (
    DecisionAutonomyController,
)
from disaster_monitor.application.services.decision_support import (
    DecisionOptionGenerator,
)
from disaster_monitor.domain.disaster import EvidenceWorldState


@dataclass(frozen=True, slots=True)
class DecisionToolDependencies:
    option_generator: DecisionOptionGenerator
    autonomy: DecisionAutonomyController
    handoff_planner: CoordinationHandoffPlanner


class DecisionTools:
    """Populate optional decision artifacts without owning evidence mechanics."""

    def __init__(self, dependencies: DecisionToolDependencies) -> None:
        self._dependencies = dependencies

    def apply(
        self, state: AgentExecutionState, evidence_state: EvidenceWorldState
    ) -> None:
        self._add_evidence_handoff(state, evidence_state)
        if InformationNeed.DECISION_SUPPORT not in state.task.information_needs:
            return
        priority = state.workspace.incident_priority
        triage_decision = state.workspace.triage_decision
        if priority is None or triage_decision is None:
            raise ValueError("Decision support requires completed triage artifacts.")
        try:
            decision_support = self._dependencies.option_generator.generate(
                evidence_state,
                state.workspace.hypotheses,
                priority,
                triage_decision,
            )
            state.workspace.decision_support = decision_support
            state.workspace.decision_outcome = self._dependencies.autonomy.execute(
                decision_support
            )
        except ValueError:
            state.capability_gaps.append(
                "Decision support failed its evidence-lineage safety gate; "
                "the deterministic report remains available."
            )
            return
        try:
            decision_handoff = self._dependencies.handoff_planner.for_decision_support(
                decision_support
            )
            state.workspace.specialist_handoffs = (
                *state.workspace.specialist_handoffs,
                decision_handoff,
            )
        except ValueError:
            self._record_handoff_gap(state)

    def _add_evidence_handoff(
        self, state: AgentExecutionState, evidence_state: EvidenceWorldState
    ) -> None:
        try:
            handoff = self._dependencies.handoff_planner.for_evidence_state(
                evidence_state
            )
            state.workspace.specialist_handoffs = (handoff,)
        except ValueError:
            self._record_handoff_gap(state)

    @staticmethod
    def _record_handoff_gap(state: AgentExecutionState) -> None:
        state.capability_gaps.append(
            "Typed specialist handoff failed its ownership or provenance gate; "
            "the single-supervisor path remains active."
        )
