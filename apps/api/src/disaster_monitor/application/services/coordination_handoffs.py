"""Strict broker and production planners for typed specialist handoffs."""

import re
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256

from disaster_monitor.domain.coordination import (
    CoordinationPermission,
    HandoffArtifactReference,
    HandoffArtifactType,
    SpecialistHandoff,
    SpecialistRole,
    SpecialistTaskType,
)
from disaster_monitor.domain.decision import DecisionSupportArtifact
from disaster_monitor.domain.disaster import EvidenceWorldState
from disaster_monitor.domain.multimodal import MultimodalEvidenceState

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,199}$")
_TASK_OWNER = {
    SpecialistTaskType.VERIFY_EVENT_IDENTITY: SpecialistRole.EVENT_IDENTITY,
    SpecialistTaskType.REVIEW_EVIDENCE_STATE: SpecialistRole.EVIDENCE_RECONCILIATION,
    SpecialistTaskType.ASSESS_DECISION_OPTIONS: SpecialistRole.DECISION_ANALYSIS,
    SpecialistTaskType.REVIEW_MULTIMODAL_STATE: SpecialistRole.MULTIMODAL_ANALYSIS,
}
_TASK_ARTIFACT = {
    SpecialistTaskType.VERIFY_EVENT_IDENTITY: HandoffArtifactType.PHYSICAL_EVENT,
    SpecialistTaskType.REVIEW_EVIDENCE_STATE: HandoffArtifactType.EVIDENCE_STATE,
    SpecialistTaskType.ASSESS_DECISION_OPTIONS: HandoffArtifactType.DECISION_SUPPORT,
    SpecialistTaskType.REVIEW_MULTIMODAL_STATE: HandoffArtifactType.MULTIMODAL_STATE,
}
_ROLE_PERMISSIONS = {
    SpecialistRole.SUPERVISOR: frozenset(
        {
            CoordinationPermission.READ_EVENT_IDENTITY,
            CoordinationPermission.READ_EVIDENCE_STATE,
            CoordinationPermission.READ_DECISION_SUPPORT,
            CoordinationPermission.READ_MULTIMODAL_STATE,
            CoordinationPermission.READ_PROVENANCE,
            CoordinationPermission.PROPOSE_ANALYSIS,
        }
    ),
    SpecialistRole.EVENT_IDENTITY: frozenset(
        {
            CoordinationPermission.READ_EVENT_IDENTITY,
            CoordinationPermission.READ_PROVENANCE,
            CoordinationPermission.PROPOSE_ANALYSIS,
        }
    ),
    SpecialistRole.EVIDENCE_RECONCILIATION: frozenset(
        {
            CoordinationPermission.READ_EVIDENCE_STATE,
            CoordinationPermission.READ_PROVENANCE,
            CoordinationPermission.PROPOSE_ANALYSIS,
        }
    ),
    SpecialistRole.DECISION_ANALYSIS: frozenset(
        {
            CoordinationPermission.READ_EVIDENCE_STATE,
            CoordinationPermission.READ_DECISION_SUPPORT,
            CoordinationPermission.READ_PROVENANCE,
            CoordinationPermission.PROPOSE_ANALYSIS,
        }
    ),
    SpecialistRole.MULTIMODAL_ANALYSIS: frozenset(
        {
            CoordinationPermission.READ_EVIDENCE_STATE,
            CoordinationPermission.READ_MULTIMODAL_STATE,
            CoordinationPermission.READ_PROVENANCE,
            CoordinationPermission.PROPOSE_ANALYSIS,
        }
    ),
}


class SpecialistHandoffBroker:
    """Issue a handoff only when ownership, provenance, and role policy agree."""

    def issue(
        self,
        *,
        task_id: str,
        task_type: SpecialistTaskType,
        sender_role: SpecialistRole,
        receiver_role: SpecialistRole,
        artifact_references: tuple[HandoffArtifactReference, ...],
        requested_permissions: tuple[CoordinationPermission, ...],
        issued_at: datetime,
    ) -> SpecialistHandoff:
        if not _SAFE_ID.fullmatch(task_id):
            raise ValueError("Handoff task ID is malformed.")
        owner = _TASK_OWNER[task_type]
        if receiver_role != owner:
            raise ValueError("Handoff receiver does not own the declared task type.")
        if len(requested_permissions) != len(set(requested_permissions)):
            raise ValueError("Handoff permissions must be unique.")
        if not set(requested_permissions) <= _ROLE_PERMISSIONS[receiver_role]:
            raise ValueError("Handoff requested privilege beyond receiver role.")
        expected_artifact = _TASK_ARTIFACT[task_type]
        if not artifact_references or any(
            item.artifact_type != expected_artifact for item in artifact_references
        ):
            raise ValueError("Handoff artifact type is ambiguous for task ownership.")
        material = "|".join(
            (
                task_id,
                task_type.value,
                sender_role.value,
                receiver_role.value,
                *(item.artifact_id for item in artifact_references),
                *(item.value for item in requested_permissions),
            )
        )
        handoff = SpecialistHandoff(
            handoff_id=(f"handoff:{sha256(material.encode('utf-8')).hexdigest()[:24]}"),
            task_id=task_id,
            task_type=task_type,
            sender_role=sender_role,
            receiver_role=receiver_role,
            owner_role=owner,
            artifact_references=artifact_references,
            requested_permissions=requested_permissions,
            granted_permissions=requested_permissions,
            issued_at=issued_at,
        )
        validate_specialist_handoff(handoff)
        return handoff

    def parse_and_issue(
        self, payload: Mapping[str, object], *, issued_at: datetime
    ) -> SpecialistHandoff:
        expected_keys = {
            "task_id",
            "task_type",
            "sender_role",
            "receiver_role",
            "artifact_references",
            "requested_permissions",
        }
        if set(payload) != expected_keys:
            raise ValueError("Handoff payload has missing or unknown fields.")
        task_id = _bounded_string(payload["task_id"], "task_id")
        try:
            task_type = SpecialistTaskType(
                _bounded_string(payload["task_type"], "task_type")
            )
            sender_role = SpecialistRole(
                _bounded_string(payload["sender_role"], "sender_role")
            )
            receiver_role = SpecialistRole(
                _bounded_string(payload["receiver_role"], "receiver_role")
            )
            requested_permissions = tuple(
                CoordinationPermission(value)
                for value in _string_list(
                    payload["requested_permissions"],
                    "requested_permissions",
                    maximum=16,
                )
            )
        except ValueError as error:
            raise ValueError(
                "Handoff payload contains an unknown enum value."
            ) from error
        raw_references = payload["artifact_references"]
        if not isinstance(raw_references, list) or not 1 <= len(raw_references) <= 4:
            raise ValueError("Handoff requires one to four artifact references.")
        references = tuple(_artifact_reference(item) for item in raw_references)
        return self.issue(
            task_id=task_id,
            task_type=task_type,
            sender_role=sender_role,
            receiver_role=receiver_role,
            artifact_references=references,
            requested_permissions=requested_permissions,
            issued_at=issued_at,
        )


class CoordinationHandoffPlanner:
    """Create canonical production handoffs from trusted workspace artifacts."""

    def __init__(self, broker: SpecialistHandoffBroker | None = None) -> None:
        self._broker = broker or SpecialistHandoffBroker()

    def for_evidence_state(self, state: EvidenceWorldState) -> SpecialistHandoff:
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    state.physical_event.physical_event_id,
                    *(
                        item.observation.observation_id
                        for claim in state.claims
                        for item in claim.history
                    ),
                )
            )
        )
        source_ids = tuple(
            dict.fromkeys(
                (
                    state.physical_event.event.source.source_id,
                    *(
                        item.observation.fact.source.source_id
                        for claim in state.claims
                        for item in claim.history
                    ),
                )
            )
        )
        reference = HandoffArtifactReference(
            artifact_id=state.state_version,
            artifact_type=HandoffArtifactType.EVIDENCE_STATE,
            state_version=state.state_version,
            evidence_ids=evidence_ids,
            source_ids=source_ids,
        )
        return self._broker.issue(
            task_id=f"task:evidence:{state.state_version.split(':')[-1]}",
            task_type=SpecialistTaskType.REVIEW_EVIDENCE_STATE,
            sender_role=SpecialistRole.SUPERVISOR,
            receiver_role=SpecialistRole.EVIDENCE_RECONCILIATION,
            artifact_references=(reference,),
            requested_permissions=(
                CoordinationPermission.READ_EVIDENCE_STATE,
                CoordinationPermission.READ_PROVENANCE,
                CoordinationPermission.PROPOSE_ANALYSIS,
            ),
            issued_at=state.evaluated_at,
        )

    def for_decision_support(
        self, artifact: DecisionSupportArtifact
    ) -> SpecialistHandoff:
        reference = HandoffArtifactReference(
            artifact_id=artifact.artifact_id,
            artifact_type=HandoffArtifactType.DECISION_SUPPORT,
            state_version=artifact.evidence_state_version,
            evidence_ids=tuple(
                dict.fromkeys(
                    evidence_id
                    for fact in artifact.facts
                    for evidence_id in fact.evidence_ids
                )
            ),
            source_ids=tuple(
                dict.fromkeys(
                    source_id
                    for fact in artifact.facts
                    for source_id in fact.source_ids
                )
            ),
        )
        return self._broker.issue(
            task_id=f"task:decision:{artifact.artifact_id.split(':')[-1]}",
            task_type=SpecialistTaskType.ASSESS_DECISION_OPTIONS,
            sender_role=SpecialistRole.SUPERVISOR,
            receiver_role=SpecialistRole.DECISION_ANALYSIS,
            artifact_references=(reference,),
            requested_permissions=(
                CoordinationPermission.READ_EVIDENCE_STATE,
                CoordinationPermission.READ_DECISION_SUPPORT,
                CoordinationPermission.READ_PROVENANCE,
                CoordinationPermission.PROPOSE_ANALYSIS,
            ),
            issued_at=artifact.generated_at,
        )

    def for_multimodal_state(self, state: MultimodalEvidenceState) -> SpecialistHandoff:
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    *(item.observation_id for item in state.observations),
                    *(item.asset_id for item in state.assets),
                )
            )
        )
        reference = HandoffArtifactReference(
            artifact_id=state.state_version,
            artifact_type=HandoffArtifactType.MULTIMODAL_STATE,
            state_version=state.evidence_world_state_version,
            evidence_ids=evidence_ids,
            source_ids=tuple(
                dict.fromkeys(item.source.source_id for item in state.assets)
            ),
        )
        return self._broker.issue(
            task_id=f"task:multimodal:{state.state_version.split(':')[-1]}",
            task_type=SpecialistTaskType.REVIEW_MULTIMODAL_STATE,
            sender_role=SpecialistRole.SUPERVISOR,
            receiver_role=SpecialistRole.MULTIMODAL_ANALYSIS,
            artifact_references=(reference,),
            requested_permissions=(
                CoordinationPermission.READ_EVIDENCE_STATE,
                CoordinationPermission.READ_MULTIMODAL_STATE,
                CoordinationPermission.READ_PROVENANCE,
                CoordinationPermission.PROPOSE_ANALYSIS,
            ),
            issued_at=state.evaluated_at,
        )


def validate_specialist_handoff(handoff: SpecialistHandoff) -> None:
    if handoff.owner_role != _TASK_OWNER[handoff.task_type]:
        raise ValueError("Handoff task ownership is invalid.")
    if handoff.receiver_role != handoff.owner_role:
        raise ValueError("Handoff receiver does not own the task.")
    if not set(handoff.granted_permissions) <= _ROLE_PERMISSIONS[handoff.receiver_role]:
        raise ValueError("Handoff amplified receiver privilege.")
    if any(
        item.artifact_type != _TASK_ARTIFACT[handoff.task_type]
        or not item.evidence_ids
        or not item.source_ids
        or not item.state_version
        for item in handoff.artifact_references
    ):
        raise ValueError("Handoff lost artifact provenance or type ownership.")


def role_permissions(role: SpecialistRole) -> frozenset[CoordinationPermission]:
    return _ROLE_PERMISSIONS[role]


def task_owner(task_type: SpecialistTaskType) -> SpecialistRole:
    return _TASK_OWNER[task_type]


def _artifact_reference(value: object) -> HandoffArtifactReference:
    if not isinstance(value, Mapping):
        raise ValueError("Handoff artifact reference must be an object.")
    expected = {
        "artifact_id",
        "artifact_type",
        "state_version",
        "evidence_ids",
        "source_ids",
    }
    if set(value) != expected:
        raise ValueError("Handoff artifact reference has invalid fields.")
    try:
        artifact_type = HandoffArtifactType(
            _bounded_string(value["artifact_type"], "artifact_type")
        )
    except ValueError as error:
        raise ValueError("Handoff artifact type is invalid.") from error
    return HandoffArtifactReference(
        artifact_id=_bounded_string(value["artifact_id"], "artifact_id"),
        artifact_type=artifact_type,
        state_version=_bounded_string(value["state_version"], "state_version"),
        evidence_ids=tuple(
            _string_list(value["evidence_ids"], "evidence_ids", maximum=128)
        ),
        source_ids=tuple(_string_list(value["source_ids"], "source_ids", maximum=64)),
    )


def _bounded_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"Handoff {field} must be a bounded string.")
    return value.strip()


def _string_list(value: object, field: str, *, maximum: int) -> list[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= maximum
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(f"Handoff {field} must be a bounded string list.")
    return [item.strip() for item in value]
