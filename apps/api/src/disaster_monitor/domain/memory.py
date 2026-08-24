"""Typed historical memory with no current-evidence authority."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MemoryType(StrEnum):
    CONVERSATION_CONTEXT = "conversation_context"
    PHYSICAL_EVENT_REFERENCE = "physical_event_reference"


class MemoryLifecycleStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DELETED = "deleted"


class MemoryAuthority(StrEnum):
    HISTORICAL_CONTEXT = "historical_context"


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """Untrusted proposal that cannot write persistence directly."""

    candidate_id: str
    schema_version: str
    memory_type: MemoryType
    summary: str
    conversation_id: str
    physical_event_id: str | None
    disaster_identifier: str | None
    country_code: str | None
    source_message_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    world_state_version: str | None
    created_at: datetime
    confirmed_at: datetime
    expires_at: datetime | None
    confidence: float
    authority: MemoryAuthority = MemoryAuthority.HISTORICAL_CONTEXT
    may_satisfy_current_evidence: bool = False

    def __post_init__(self) -> None:
        _validate_common(
            stable_id=self.candidate_id,
            schema_version=self.schema_version,
            memory_type=self.memory_type,
            summary=self.summary,
            conversation_id=self.conversation_id,
            physical_event_id=self.physical_event_id,
            disaster_identifier=self.disaster_identifier,
            country_code=self.country_code,
            source_message_ids=self.source_message_ids,
            evidence_ids=self.evidence_ids,
            world_state_version=self.world_state_version,
            created_at=self.created_at,
            confirmed_at=self.confirmed_at,
            expires_at=self.expires_at,
            authority=self.authority,
            may_satisfy_current_evidence=self.may_satisfy_current_evidence,
        )
        if not 0 <= self.confidence <= 1:
            raise ValueError("Memory candidate confidence must be bounded.")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    memory_id: str
    schema_version: str
    memory_type: MemoryType
    status: MemoryLifecycleStatus
    summary: str
    conversation_id: str
    physical_event_id: str | None
    disaster_identifier: str | None
    country_code: str | None
    source_message_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    world_state_version: str | None
    created_at: datetime
    confirmed_at: datetime
    expires_at: datetime | None
    superseded_by_memory_id: str | None = None
    deleted_at: datetime | None = None
    authority: MemoryAuthority = MemoryAuthority.HISTORICAL_CONTEXT
    may_satisfy_current_evidence: bool = False

    def __post_init__(self) -> None:
        _validate_common(
            stable_id=self.memory_id,
            schema_version=self.schema_version,
            memory_type=self.memory_type,
            summary=self.summary,
            conversation_id=self.conversation_id,
            physical_event_id=self.physical_event_id,
            disaster_identifier=self.disaster_identifier,
            country_code=self.country_code,
            source_message_ids=self.source_message_ids,
            evidence_ids=self.evidence_ids,
            world_state_version=self.world_state_version,
            created_at=self.created_at,
            confirmed_at=self.confirmed_at,
            expires_at=self.expires_at,
            authority=self.authority,
            may_satisfy_current_evidence=self.may_satisfy_current_evidence,
        )
        if self.status is MemoryLifecycleStatus.ACTIVE:
            if self.superseded_by_memory_id is not None or self.deleted_at is not None:
                raise ValueError("Active memory cannot be superseded or deleted.")
        elif self.status is MemoryLifecycleStatus.SUPERSEDED:
            if not self.superseded_by_memory_id or self.deleted_at is not None:
                raise ValueError("Superseded memory requires replacement lineage.")
        elif self.status is MemoryLifecycleStatus.EXPIRED:
            if self.expires_at is None or self.deleted_at is not None:
                raise ValueError("Expired memory requires an expiry timestamp.")
        elif self.deleted_at is None:
            raise ValueError("Deleted memory requires a deletion timestamp.")


@dataclass(frozen=True, slots=True)
class MemoryContextItem:
    memory_id: str
    memory_type: MemoryType
    summary: str
    conversation_id: str
    physical_event_id: str | None
    disaster_identifier: str | None
    country_code: str | None
    source_message_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    world_state_version: str | None
    confirmed_at: datetime
    authority: MemoryAuthority = MemoryAuthority.HISTORICAL_CONTEXT
    may_satisfy_current_evidence: bool = False


@dataclass(frozen=True, slots=True)
class MemoryContextArtifact:
    context_id: str
    conversation_id: str
    physical_event_id: str | None
    records: tuple[MemoryContextItem, ...]
    created_at: datetime
    total_characters: int
    maximum_records: int
    maximum_characters: int
    authority: MemoryAuthority = MemoryAuthority.HISTORICAL_CONTEXT
    may_satisfy_current_evidence: bool = False

    def __post_init__(self) -> None:
        if not self.context_id or not self.conversation_id:
            raise ValueError("Memory context requires stable conversation lineage.")
        if self.maximum_records < 1 or self.maximum_records > 5:
            raise ValueError("Memory context record budget must not exceed five.")
        if self.maximum_characters < 1:
            raise ValueError("Memory context character budget must be positive.")
        if len(self.records) > self.maximum_records:
            raise ValueError("Memory context exceeded its record budget.")
        if not 0 <= self.total_characters <= self.maximum_characters:
            raise ValueError("Memory context exceeded its character budget.")
        if (
            self.authority is not MemoryAuthority.HISTORICAL_CONTEXT
            or self.may_satisfy_current_evidence
            or any(
                item.authority is not MemoryAuthority.HISTORICAL_CONTEXT
                or item.may_satisfy_current_evidence
                for item in self.records
            )
        ):
            raise ValueError("Memory context cannot acquire evidence authority.")


def _validate_common(
    *,
    stable_id: str,
    schema_version: str,
    memory_type: MemoryType,
    summary: str,
    conversation_id: str,
    physical_event_id: str | None,
    disaster_identifier: str | None,
    country_code: str | None,
    source_message_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    world_state_version: str | None,
    created_at: datetime,
    confirmed_at: datetime,
    expires_at: datetime | None,
    authority: MemoryAuthority,
    may_satisfy_current_evidence: bool,
) -> None:
    if not all((stable_id.strip(), schema_version.strip(), conversation_id.strip())):
        raise ValueError("Memory requires stable identity and conversation scope.")
    if not summary.strip() or len(summary) > 500:
        raise ValueError("Memory summary must be present and bounded.")
    if not source_message_ids or len(source_message_ids) != len(
        set(source_message_ids)
    ):
        raise ValueError("Memory requires unique source-message lineage.")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("Memory evidence references must be unique.")
    if any(value.utcoffset() is None for value in (created_at, confirmed_at)):
        raise ValueError("Memory timestamps must be timezone-aware.")
    if confirmed_at < created_at:
        raise ValueError("Memory confirmation cannot precede creation.")
    if expires_at is not None and expires_at.utcoffset() is None:
        raise ValueError("Memory expiry must be timezone-aware.")
    if memory_type is MemoryType.PHYSICAL_EVENT_REFERENCE and not all(
        (
            physical_event_id,
            disaster_identifier,
            country_code,
            evidence_ids,
            world_state_version,
        )
    ):
        raise ValueError("Physical-event memory requires reference-only provenance.")
    if country_code is not None and len(country_code) != 3:
        raise ValueError("Memory country identifier must be ISO alpha-3.")
    if (
        authority is not MemoryAuthority.HISTORICAL_CONTEXT
        or may_satisfy_current_evidence
    ):
        raise ValueError("Memory cannot satisfy current evidence authority.")
