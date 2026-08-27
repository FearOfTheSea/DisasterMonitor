"""Record an attributable operator review of a durable evidence state."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.services.operational_ingestion import (
    record_operator_review,
)
from disaster_monitor.domain.operations import OperatorActionRecord, OperatorDecision


class UnknownEvidenceStateError(ValueError):
    """The operator review references a world state that was not persisted."""


@dataclass(frozen=True, slots=True)
class RecordOperatorActionResult:
    action: OperatorActionRecord
    created: bool


class RecordOperatorAction:
    """Construct and persist a bounded operator review and audit projection."""

    def __init__(
        self,
        repository: OperationalRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        identifier: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._identifier = identifier

    async def execute(
        self,
        *,
        operator_id: str,
        decision: OperatorDecision,
        state_version: str,
        rationale: str,
        evidence_ids: tuple[str, ...] = (),
        policy_ids: tuple[str, ...] = (),
    ) -> RecordOperatorActionResult:
        if not await self._repository.world_state_exists(state_version):
            raise UnknownEvidenceStateError(state_version)
        action = OperatorActionRecord(
            action_id=f"operator-action:{self._identifier()}",
            operator_id=operator_id,
            decision=decision,
            state_version=state_version,
            rationale=rationale,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            policy_ids=tuple(dict.fromkeys(policy_ids)),
            reviewed_at=self._clock(),
        )
        return RecordOperatorActionResult(
            action=action,
            created=await record_operator_review(self._repository, action),
        )
