"""Typed specialist coordination artifacts with closed authority boundaries."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SpecialistRole(StrEnum):
    SUPERVISOR = "supervisor"
    EVENT_IDENTITY = "event_identity_specialist"
    EVIDENCE_RECONCILIATION = "evidence_reconciliation_specialist"
    DECISION_ANALYSIS = "decision_analysis_specialist"
    MULTIMODAL_ANALYSIS = "multimodal_analysis_specialist"


class SpecialistTaskType(StrEnum):
    VERIFY_EVENT_IDENTITY = "verify_event_identity"
    REVIEW_EVIDENCE_STATE = "review_evidence_state"
    ASSESS_DECISION_OPTIONS = "assess_decision_options"
    REVIEW_MULTIMODAL_STATE = "review_multimodal_state"


class CoordinationPermission(StrEnum):
    READ_EVENT_IDENTITY = "read_event_identity"
    READ_EVIDENCE_STATE = "read_evidence_state"
    READ_DECISION_SUPPORT = "read_decision_support"
    READ_MULTIMODAL_STATE = "read_multimodal_state"
    READ_PROVENANCE = "read_provenance"
    PROPOSE_ANALYSIS = "propose_analysis"
    EXECUTE_PROVIDER_IO = "execute_provider_io"
    ALTER_SAFETY_POLICY = "alter_safety_policy"


class HandoffArtifactType(StrEnum):
    PHYSICAL_EVENT = "physical_event"
    EVIDENCE_STATE = "evidence_state"
    DECISION_SUPPORT = "decision_support"
    MULTIMODAL_STATE = "multimodal_state"


class CollaborativeInvestigationStatus(StrEnum):
    COMPLETED = "completed"
    SINGLE_SUPERVISOR_FALLBACK = "single_supervisor_fallback"


class CoordinationSupervisorStatus(StrEnum):
    AUTONOMOUS_COMPLETE = "autonomous_complete"
    DEFAULT_PLAN_FALLBACK = "default_plan_fallback"


@dataclass(frozen=True, slots=True)
class HandoffArtifactReference:
    artifact_id: str
    artifact_type: HandoffArtifactType
    state_version: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(
            (self.artifact_id, self.state_version, self.evidence_ids, self.source_ids)
        ):
            raise ValueError("Handoff artifacts require complete provenance.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Handoff evidence IDs must be unique.")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Handoff source IDs must be unique.")


@dataclass(frozen=True, slots=True)
class SpecialistHandoff:
    handoff_id: str
    task_id: str
    task_type: SpecialistTaskType
    sender_role: SpecialistRole
    receiver_role: SpecialistRole
    owner_role: SpecialistRole
    artifact_references: tuple[HandoffArtifactReference, ...]
    requested_permissions: tuple[CoordinationPermission, ...]
    granted_permissions: tuple[CoordinationPermission, ...]
    issued_at: datetime

    def __post_init__(self) -> None:
        if not self.handoff_id or not self.task_id:
            raise ValueError("Specialist handoff requires stable task identity.")
        if self.sender_role == self.receiver_role:
            raise ValueError(
                "Specialist handoff requires distinct sender and receiver."
            )
        if self.owner_role != self.receiver_role:
            raise ValueError("Receiving specialist must own the handed-off task.")
        if not self.artifact_references:
            raise ValueError("Specialist handoff requires typed artifacts.")
        if not self.requested_permissions or not self.granted_permissions:
            raise ValueError("Specialist handoff requires explicit permissions.")
        if self.granted_permissions != self.requested_permissions:
            raise ValueError(
                "Handoff permissions cannot be silently broadened or reduced."
            )


@dataclass(frozen=True, slots=True)
class SpecialistFindingDraft:
    """Untrusted model proposal that requires application-owned validation."""

    specialist_role: SpecialistRole
    task_type: SpecialistTaskType
    finding_key: str
    value: str
    summary: str
    state_version: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    permissions: tuple[CoordinationPermission, ...]
    safety_policy_fingerprint: str

    def __post_init__(self) -> None:
        texts = (
            self.finding_key,
            self.value,
            self.summary,
            self.state_version,
            self.safety_policy_fingerprint,
        )
        if any(not value.strip() for value in texts):
            raise ValueError("Specialist draft fields must not be empty.")
        if len(self.finding_key) > 200 or len(self.value) > 500:
            raise ValueError("Specialist draft values must be bounded.")
        if len(self.summary) > 1_000:
            raise ValueError("Specialist draft summary must be bounded.")
        if not self.evidence_ids or not self.source_ids or not self.permissions:
            raise ValueError("Specialist drafts require explicit lineage and scope.")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Specialist draft evidence IDs must be unique.")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Specialist draft source IDs must be unique.")
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("Specialist draft permissions must be unique.")


@dataclass(frozen=True, slots=True)
class SpecialistFinding:
    finding_id: str
    specialist_role: SpecialistRole
    finding_key: str
    value: str
    summary: str
    state_version: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    safety_policy_fingerprint: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.finding_id,
                self.finding_key,
                self.value,
                self.summary.strip(),
                self.state_version,
                self.evidence_ids,
                self.source_ids,
                self.safety_policy_fingerprint,
            )
        ):
            raise ValueError("Specialist findings require content and provenance.")
        if self.specialist_role == SpecialistRole.SUPERVISOR:
            raise ValueError("Supervisor output is not a specialist finding.")


@dataclass(frozen=True, slots=True)
class CollaborativeInvestigation:
    investigation_id: str
    status: CollaborativeInvestigationStatus
    evidence_state_version: str
    handoff_ids: tuple[str, ...]
    findings: tuple[SpecialistFinding, ...]
    participating_roles: tuple[SpecialistRole, ...]
    unresolved_deadlocks: tuple[str, ...]
    iterations: int
    safety_policy_fingerprint: str
    fallback_reason: str | None

    def __post_init__(self) -> None:
        if not self.investigation_id or not self.evidence_state_version:
            raise ValueError("Collaborative investigation requires state lineage.")
        if not 1 <= self.iterations <= 2:
            raise ValueError("Collaborative investigation exceeded iteration budget.")
        if not self.safety_policy_fingerprint:
            raise ValueError("Collaborative investigation requires safety fingerprint.")
        if self.status == CollaborativeInvestigationStatus.COMPLETED:
            if (
                len(self.participating_roles) < 2
                or self.unresolved_deadlocks
                or self.fallback_reason is not None
                or not self.findings
            ):
                raise ValueError(
                    "Completed collaboration requires findings from two specialists."
                )
        elif self.fallback_reason is None:
            raise ValueError("Single-supervisor fallback requires a visible reason.")


@dataclass(frozen=True, slots=True)
class CoordinationSupervision:
    supervision_id: str
    status: CoordinationSupervisorStatus
    evidence_state_version: str
    collaboration: CollaborativeInvestigation
    sufficient: bool
    required_finding_keys: tuple[str, ...]
    missing_finding_keys: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    final_rationale: str
    termination_reason: str
    handoff_count: int
    finding_count: int
    iterations: int
    max_handoffs: int
    max_findings: int
    max_iterations: int
    safety_policy_fingerprint: str
    analytical_focus: str
    analytical_parameter_set_id: str
    analytical_release_id: str

    def __post_init__(self) -> None:
        if not self.supervision_id or not self.evidence_state_version:
            raise ValueError("Coordination supervision requires stable state lineage.")
        if self.collaboration.evidence_state_version != self.evidence_state_version:
            raise ValueError("Coordination supervision escaped collaboration state.")
        if not self.required_finding_keys:
            raise ValueError(
                "Coordination supervision requires a sufficiency checklist."
            )
        if not self.evidence_ids or not self.source_ids:
            raise ValueError(
                "Coordination supervision requires inspectable provenance."
            )
        if not self.final_rationale.strip() or len(self.final_rationale) > 1_000:
            raise ValueError(
                "Coordination supervision requires bounded final rationale."
            )
        if not self.termination_reason:
            raise ValueError("Coordination supervision requires explicit termination.")
        if not all(
            (
                self.analytical_focus,
                self.analytical_parameter_set_id,
                self.analytical_release_id,
            )
        ):
            raise ValueError("Coordination supervision requires tuning provenance.")
        if (
            self.handoff_count < 0
            or self.finding_count < 0
            or self.iterations < 1
            or self.max_handoffs <= 0
            or self.max_findings <= 0
            or self.max_iterations <= 0
        ):
            raise ValueError("Coordination supervision budgets must be positive.")
        if self.status == CoordinationSupervisorStatus.AUTONOMOUS_COMPLETE:
            if (
                not self.sufficient
                or self.missing_finding_keys
                or self.collaboration.status
                != CollaborativeInvestigationStatus.COMPLETED
                or self.handoff_count > self.max_handoffs
                or self.finding_count > self.max_findings
                or self.iterations > self.max_iterations
            ):
                raise ValueError(
                    "Autonomous coordination requires sufficient bounded completion."
                )
        elif self.sufficient:
            raise ValueError(
                "Default-plan fallback cannot claim sufficient completion."
            )
