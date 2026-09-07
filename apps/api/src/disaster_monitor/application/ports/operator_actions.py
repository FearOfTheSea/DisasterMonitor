"""Ports for durable evidence snapshots, jobs, history, and attribution."""

from typing import Protocol

from disaster_monitor.domain.operations import (
    AuditEventRecord,
    OperatorActionRecord,
)


class OperatorActionStore(Protocol):
    async def world_state_exists(self, state_version: str) -> bool: ...

    async def record_operator_action(self, action: OperatorActionRecord) -> bool: ...

    async def append_audit_event(self, event: AuditEventRecord) -> bool: ...
