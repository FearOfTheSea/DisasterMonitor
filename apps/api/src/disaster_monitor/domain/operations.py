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


class ProviderHealthState(StrEnum):
    """Operational posture; it is not a statement that a hazard is absent."""

    HEALTHY = "healthy"
    STALE = "stale"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    MISCONFIGURED = "misconfigured"


class ProviderAttemptOutcome(StrEnum):
    """Outcome of one bounded provider acquisition attempt."""

    SUCCESS = "success"
    EMPTY = "empty"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


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
class ProviderAttempt:
    """Durable, source-scoped outcome metadata without raw provider payloads."""

    source_id: str
    attempted_at: datetime
    outcome: ProviderAttemptOutcome
    reason_code: str | None = None
    retryable: bool = False
    http_status: int | None = None
    records_seen: int = 0
    published_at: datetime | None = None
    parse_failure: bool = False
    admission_failure: bool = False
    truncated: bool = False
    hazard: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id.strip() or self.attempted_at.tzinfo is None:
            raise ValueError("Provider attempts require a source and aware time.")
        if self.records_seen < 0:
            raise ValueError("Provider attempt record counts cannot be negative.")
        for value in (self.published_at,):
            if value is not None and value.tzinfo is None:
                raise ValueError("Provider attempt publication times must be aware.")


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
    lease_expires_at: datetime | None = None
    fencing_token: int = 0
    last_failed_at: datetime | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id or not self.source_id or not self.canonical_request_identity:
            raise ValueError("Ingest jobs require stable source and request identity.")
        if self.scheduled_for.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("Ingest job times must be timezone-aware.")
        if self.attempt_count < 0 or self.max_attempts < 1:
            raise ValueError("Ingest job attempt limits are invalid.")
        if self.fencing_token < 0:
            raise ValueError("Ingest job fencing tokens cannot be negative.")
        for value in (self.claimed_at, self.lease_expires_at, self.last_failed_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Ingest job lease and failure times must be aware.")


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
    health_state: ProviderHealthState = ProviderHealthState.MISCONFIGURED
    source_publication_age_seconds: int | None = None
    retrieval_lag_seconds: int | None = None
    parse_failures: int = 0
    admission_failures: int = 0
    truncated: bool = False
    stale_projection_age_seconds: int | None = None
    hazard: str | None = None


def current_attempt_diagnostics(
    attempts: tuple[ProviderAttempt, ...],
) -> tuple[int, int, bool, str | None]:
    """Summarize only the current attempt or its consecutive failure run."""
    active: list[ProviderAttempt] = []
    for attempt in attempts:
        if active and attempt.outcome not in {
            ProviderAttemptOutcome.FAILED,
            ProviderAttemptOutcome.INCOMPLETE,
        }:
            break
        active.append(attempt)
        if attempt.outcome not in {
            ProviderAttemptOutcome.FAILED,
            ProviderAttemptOutcome.INCOMPLETE,
        }:
            break
    return (
        sum(item.parse_failure for item in active),
        sum(item.admission_failure for item in active),
        any(item.truncated for item in active),
        next((item.hazard for item in active if item.hazard is not None), None),
    )


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
    source_publication_age_seconds: int | None = None,
    retrieval_lag_seconds: int | None = None,
    parse_failures: int = 0,
    admission_failures: int = 0,
    truncated: bool = False,
    stale_projection_age_seconds: int | None = None,
    hazard: str | None = None,
    configured: bool = True,
) -> ProviderFreshness:
    """Classify freshness without hiding upstream acquisition failures."""
    if last_snapshot is None:
        state = (
            FreshnessState.UNAVAILABLE
            if consecutive_failures
            else FreshnessState.NEVER_INGESTED
        )
        health = (
            ProviderHealthState.MISCONFIGURED
            if not configured
            else ProviderHealthState.UNAVAILABLE
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
            health,
            source_publication_age_seconds,
            retrieval_lag_seconds,
            parse_failures,
            admission_failures,
            truncated,
            stale_projection_age_seconds,
            hazard,
        )
    age = max(0, int((now - last_snapshot.effective_at).total_seconds()))
    state = (
        FreshnessState.FRESH
        if age <= expected_freshness.total_seconds()
        else FreshnessState.STALE
    )
    health = (
        ProviderHealthState.MISCONFIGURED
        if not configured
        else ProviderHealthState.DEGRADED
        if consecutive_failures or parse_failures or admission_failures or truncated
        else ProviderHealthState.STALE
        if state is FreshnessState.STALE
        else ProviderHealthState.HEALTHY
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
        health,
        source_publication_age_seconds,
        retrieval_lag_seconds,
        parse_failures,
        admission_failures,
        truncated,
        stale_projection_age_seconds,
        hazard,
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
