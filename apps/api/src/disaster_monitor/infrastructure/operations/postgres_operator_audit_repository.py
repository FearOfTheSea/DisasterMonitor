"""PostgreSQL persistence for attributable operator actions and audit events."""

import json

from disaster_monitor.domain.operations import AuditEventRecord, OperatorActionRecord
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresOperatorAuditRepository(PostgresRepositoryBase):
    """Persist bounded human review records and public audit metadata."""

    async def record_operator_action(self, action: OperatorActionRecord) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO operator_action(
                        action_id, operator_id, decision, state_version, rationale,
                        evidence_ids, policy_ids, reviewed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                    ON CONFLICT (action_id) DO NOTHING
                    """,
                    (
                        action.action_id,
                        action.operator_id,
                        action.decision.value,
                        action.state_version,
                        action.rationale,
                        json.dumps(action.evidence_ids),
                        json.dumps(action.policy_ids),
                        action.reviewed_at,
                    ),
                )
                return cursor.rowcount == 1

    async def append_audit_event(self, event: AuditEventRecord) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO audit_event(
                        audit_id, event_type, subject_id, occurred_at,
                        evidence_ids, policy_ids, public_rationale
                    ) VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                    ON CONFLICT (audit_id) DO NOTHING
                    """,
                    (
                        event.audit_id,
                        event.event_type,
                        event.subject_id,
                        event.occurred_at,
                        json.dumps(event.evidence_ids),
                        json.dumps(event.policy_ids),
                        event.public_rationale,
                    ),
                )
                return cursor.rowcount == 1
