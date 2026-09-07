"""Deterministic admission and lifecycle policy for historical memory."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256

from disaster_monitor.domain.memory import (
    MemoryCandidate,
    MemoryLifecycleStatus,
    MemoryRecord,
    MemoryType,
)

MEMORY_SCHEMA_VERSION = "agent-memory.v1"
MINIMUM_MEMORY_CONFIDENCE = 0.9
DEFAULT_MEMORY_RETENTION = timedelta(days=30)


class MemoryPolicyAction(StrEnum):
    ACCEPTED = "accepted"
    MERGED = "merged"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class MemoryPolicyDecision:
    action: MemoryPolicyAction
    record: MemoryRecord | None
    superseded_memory_ids: tuple[str, ...] = ()
    reason: str | None = None


class MemoryPolicy:
    """Accept only bounded reference context and retain explicit lifecycle state."""

    def evaluate(
        self,
        candidate: MemoryCandidate,
        existing: tuple[MemoryRecord | None, ...],
        *,
        now: datetime,
    ) -> MemoryPolicyDecision:
        if candidate.schema_version != MEMORY_SCHEMA_VERSION:
            return _rejected("unsupported_memory_schema")
        if candidate.confidence < MINIMUM_MEMORY_CONFIDENCE:
            return _rejected("candidate_confidence_below_policy")
        if candidate.expires_at is not None and candidate.expires_at <= now:
            return MemoryPolicyDecision(
                MemoryPolicyAction.EXPIRED, None, reason="candidate_expired"
            )
        normalized_summary = candidate.summary.strip().casefold()
        if not normalized_summary.startswith("historical") or "http" in (
            normalized_summary
        ):
            return _rejected("volatile_or_authoritative_summary")
        if candidate.memory_type is not MemoryType.PHYSICAL_EVENT_REFERENCE:
            return _rejected("unsupported_memory_type")

        active = tuple(
            record
            for record in existing
            if record is not None
            and record.status is MemoryLifecycleStatus.ACTIVE
            and (record.expires_at is None or record.expires_at > now)
            and record.conversation_id == candidate.conversation_id
            and record.memory_type is candidate.memory_type
            and record.physical_event_id == candidate.physical_event_id
        )
        same_state = next(
            (
                record
                for record in active
                if record.world_state_version == candidate.world_state_version
            ),
            None,
        )
        if same_state is not None:
            merged = replace(
                same_state,
                summary=candidate.summary.strip(),
                source_message_ids=tuple(
                    dict.fromkeys(
                        (*same_state.source_message_ids, *candidate.source_message_ids)
                    )
                ),
                evidence_ids=tuple(
                    dict.fromkeys((*same_state.evidence_ids, *candidate.evidence_ids))
                ),
                confirmed_at=max(same_state.confirmed_at, candidate.confirmed_at),
                expires_at=_latest_expiry(same_state.expires_at, candidate.expires_at),
            )
            return MemoryPolicyDecision(MemoryPolicyAction.MERGED, merged)

        record = _record(candidate)
        if active:
            return MemoryPolicyDecision(
                MemoryPolicyAction.SUPERSEDED,
                record,
                superseded_memory_ids=tuple(
                    item.memory_id for item in sorted(active, key=_record_order)
                ),
            )
        return MemoryPolicyDecision(MemoryPolicyAction.ACCEPTED, record)

    def candidate_for_investigation(
        self,
        *,
        conversation_id: str,
        physical_event_id: str,
        disaster_identifier: str,
        country_code: str,
        source_message_ids: tuple[str, ...],
        evidence_ids: tuple[str, ...],
        world_state_version: str,
        now: datetime,
    ) -> MemoryCandidate:
        material = "|".join((conversation_id, physical_event_id, world_state_version))
        return MemoryCandidate(
            candidate_id=(
                f"candidate:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            schema_version=MEMORY_SCHEMA_VERSION,
            memory_type=MemoryType.PHYSICAL_EVENT_REFERENCE,
            summary=(
                "Historical investigation reference for "
                f"{disaster_identifier.replace('_', ' ')} in {country_code}; "
                "current conditions require newly admitted evidence."
            ),
            conversation_id=conversation_id,
            physical_event_id=physical_event_id,
            disaster_identifier=disaster_identifier,
            country_code=country_code,
            source_message_ids=source_message_ids,
            evidence_ids=evidence_ids,
            world_state_version=world_state_version,
            created_at=now,
            confirmed_at=now,
            expires_at=now + DEFAULT_MEMORY_RETENTION,
            confidence=1.0,
        )


def _record(candidate: MemoryCandidate) -> MemoryRecord:
    material = "|".join(
        (
            candidate.conversation_id,
            candidate.memory_type.value,
            candidate.physical_event_id or "",
            candidate.world_state_version or "",
        )
    )
    return MemoryRecord(
        memory_id=f"memory:{sha256(material.encode('utf-8')).hexdigest()[:24]}",
        schema_version=candidate.schema_version,
        memory_type=candidate.memory_type,
        status=MemoryLifecycleStatus.ACTIVE,
        summary=candidate.summary.strip(),
        conversation_id=candidate.conversation_id,
        physical_event_id=candidate.physical_event_id,
        disaster_identifier=candidate.disaster_identifier,
        country_code=candidate.country_code,
        source_message_ids=candidate.source_message_ids,
        evidence_ids=candidate.evidence_ids,
        world_state_version=candidate.world_state_version,
        created_at=candidate.created_at,
        confirmed_at=candidate.confirmed_at,
        expires_at=candidate.expires_at,
    )


def _rejected(reason: str) -> MemoryPolicyDecision:
    return MemoryPolicyDecision(MemoryPolicyAction.REJECTED, None, reason=reason)


def _record_order(record: MemoryRecord) -> tuple[datetime, str]:
    return record.confirmed_at, record.memory_id


def _latest_expiry(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None or second is None:
        return None
    return max(first, second)
