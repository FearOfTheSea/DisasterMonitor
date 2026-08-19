"""Stable operational records for persistent evidence ingestion and audit."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class IngestJobStatus(StrEnum):
    """Durable at-least-once queue states."""

    QUEUED = "queued"
    RUNNING = "running"
    RETRY = "retry"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"


class FreshnessState(StrEnum):
    """Machine-readable provider evidence freshness."""

    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    NEVER_INGESTED = "never_ingested"


class OperatorDecision(StrEnum):
    """Closed set of attributable reviews; no operational command is implied."""

    REVIEWED = "reviewed"
    APPROVED_BOUNDED = "approved_bounded"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SourceSnapshotRecord:
    """Append-only identity and immutable-content pointer for one response."""

    snapshot_id: str
    idempotency_key: str
    source_id: str
    canonical_request_identity: str
    provider_revision: str
    retrieved_at: datetime
    published_at: datetime | None
    observed_at: datetime | None
    response_status: int
    content_type: str
    payload_sha256: str
    payload_size_bytes: int
    blob_uri: str
    rights_id: str
    content_deleted_at: datetime | None = None
    content_deletion_reason: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.snapshot_id,
                self.idempotency_key,
                self.source_id,
                self.canonical_request_identity,
                self.provider_revision,
                self.content_type,
                self.blob_uri,
                self.rights_id,
            )
        ):
            raise ValueError("Source snapshots require complete immutable identity.")
        if not _valid_prefixed_sha256(self.payload_sha256):
            raise ValueError("Source snapshot payload checksum must be SHA-256.")
        if self.payload_size_bytes < 1:
            raise ValueError("Source snapshot payload must not be empty.")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("Source snapshot retrieval time must be timezone-aware.")
        if self.response_status < 200 or self.response_status > 299:
            raise ValueError("Only successful bounded responses can become snapshots.")
        if (self.content_deleted_at is None) != (self.content_deletion_reason is None):
            raise ValueError("Snapshot tombstones require both time and reason.")
        if (
            self.content_deleted_at is not None
            and self.content_deleted_at.tzinfo is None
        ):
            raise ValueError("Snapshot tombstone time must be timezone-aware.")

    @property
    def effective_at(self) -> datetime:
        return self.observed_at or self.published_at or self.retrieved_at

    @property
    def content_available(self) -> bool:
        return self.content_deleted_at is None


@dataclass(frozen=True, slots=True)
class IngestJob:
    """One durable acquisition request with explicit retry authority."""

    job_id: str
    source_id: str
    canonical_request_identity: str
    scheduled_for: datetime
    status: IngestJobStatus
    attempt_count: int
    max_attempts: int
    created_at: datetime
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    last_error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id or not self.source_id or not self.canonical_request_identity:
            raise ValueError("Ingest jobs require stable source and request identity.")
        if self.scheduled_for.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("Ingest job times must be timezone-aware.")
        if self.attempt_count < 0 or self.max_attempts < 1:
            raise ValueError("Ingest job attempt limits are invalid.")


@dataclass(frozen=True, slots=True)
class NormalizedObservationRecord:
    """A deterministic normalized observation with exactly one snapshot parent."""

    observation_id: str
    snapshot_id: str
    source_id: str
    observation_type: str
    effective_at: datetime
    parser_version: str
    canonical_json: str


@dataclass(frozen=True, slots=True)
class PhysicalEventRecord:
    """Durable representative identity for a conservatively resolved event."""

    physical_event_id: str
    disaster: str
    country_code: str
    latitude: float | None
    longitude: float | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EventObservationLinkRecord:
    """Auditable association from normalized evidence to a physical event."""

    physical_event_id: str
    observation_id: str
    assignment_status: str
    rationale: str


@dataclass(frozen=True, slots=True)
class WorldStateVersionRecord:
    """Persistent identity for one reproducible canonical state."""

    state_version: str
    physical_event_id: str
    source_set_sha256: str
    canonical_state_sha256: str
    policy_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not _valid_prefixed_sha256(self.source_set_sha256) or not (
            _valid_prefixed_sha256(self.canonical_state_sha256)
        ):
            raise ValueError("World-state hashes must be prefixed SHA-256 values.")


@dataclass(frozen=True, slots=True)
class ProviderFreshness:
    """Freshness and ingestion-lag status for one registered source."""

    source_id: str
    state: FreshnessState
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    effective_at: datetime | None
    age_seconds: int | None
    expected_freshness_seconds: int
    consecutive_failures: int
    latest_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorActionRecord:
    """Attributable human review of a bounded state/version."""

    action_id: str
    operator_id: str
    decision: OperatorDecision
    state_version: str
    rationale: str
    evidence_ids: tuple[str, ...]
    policy_ids: tuple[str, ...]
    reviewed_at: datetime

    def __post_init__(self) -> None:
        if not self.action_id or not self.operator_id or not self.state_version:
            raise ValueError("Operator actions require identity and state lineage.")
        if not self.rationale.strip() or len(self.rationale) > 2_000:
            raise ValueError("Operator action rationale must be bounded and non-empty.")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("Operator review time must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    """Public policy/action audit metadata without private reasoning traces."""

    audit_id: str
    event_type: str
    subject_id: str
    occurred_at: datetime
    evidence_ids: tuple[str, ...]
    policy_ids: tuple[str, ...]
    public_rationale: str


def freshness_for(
    *,
    source_id: str,
    now: datetime,
    expected_freshness: timedelta,
    last_attempt_at: datetime | None,
    last_snapshot: SourceSnapshotRecord | None,
    consecutive_failures: int,
    latest_error_code: str | None,
) -> ProviderFreshness:
    """Classify freshness without hiding upstream acquisition failures."""
    if last_snapshot is None:
        state = (
            FreshnessState.UNAVAILABLE
            if consecutive_failures
            else FreshnessState.NEVER_INGESTED
        )
        return ProviderFreshness(
            source_id,
            state,
            last_attempt_at,
            None,
            None,
            None,
            int(expected_freshness.total_seconds()),
            consecutive_failures,
            latest_error_code,
        )
    age = max(0, int((now - last_snapshot.effective_at).total_seconds()))
    state = (
        FreshnessState.FRESH
        if age <= expected_freshness.total_seconds()
        else FreshnessState.STALE
    )
    return ProviderFreshness(
        source_id,
        state,
        last_attempt_at,
        last_snapshot.retrieved_at,
        last_snapshot.effective_at,
        age,
        int(expected_freshness.total_seconds()),
        consecutive_failures,
        latest_error_code,
    )


def _valid_prefixed_sha256(value: str) -> bool:
    prefix, separator, digest = value.partition(":")
    if prefix != "sha256" or separator != ":" or len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True
