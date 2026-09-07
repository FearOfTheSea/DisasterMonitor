"""At-least-once ingestion, immutable snapshots, and bounded worker policy."""

from __future__ import annotations

from disaster_monitor.application.ports.operator_actions import OperatorActionStore
from disaster_monitor.domain.operations import (
    AuditEventRecord,
    OperatorActionRecord,
)


async def record_operator_review(
    repository: OperatorActionStore,
    action: OperatorActionRecord,
) -> bool:
    """Persist an attributable review and its public audit projection."""
    created = await repository.record_operator_action(action)
    if created:
        await repository.append_audit_event(
            AuditEventRecord(
                audit_id=f"audit:{action.action_id}",
                event_type="operator_review_recorded",
                subject_id=action.state_version,
                occurred_at=action.reviewed_at,
                evidence_ids=action.evidence_ids,
                policy_ids=action.policy_ids,
                public_rationale=action.rationale,
            )
        )
    return created
