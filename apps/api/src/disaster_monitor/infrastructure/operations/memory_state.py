"""Deterministic in-memory operational repository for tests and safe fallback."""

from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionRecord,
)
from disaster_monitor.domain.disaster import (
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchObservation,
)
from disaster_monitor.domain.news import IncidentCandidate, NewsObservation
from disaster_monitor.domain.operations import (
    AuditEventRecord,
    EventObservationLinkRecord,
    IngestJob,
    NormalizedObservationRecord,
    OperatorActionRecord,
    PhysicalEventRecord,
    ProviderAttempt,
    SourceSnapshotRecord,
    WorldStateVersionRecord,
)
from disaster_monitor.domain.web_collection import WebFetchAudit, WebFetchState


class MemoryState:
    def __init__(self) -> None:
        self.jobs: dict[str, IngestJob] = {}
        self.snapshot_records: dict[str, SourceSnapshotRecord] = {}
        self.snapshot_idempotency: dict[str, str] = {}
        self.observations: dict[str, NormalizedObservationRecord] = {}
        self.physical_events: dict[str, PhysicalEventRecord] = {}
        self.event_links: dict[tuple[str, str], EventObservationLinkRecord] = {}
        self.world_states: dict[str, WorldStateVersionRecord] = {}
        self.operator_actions: dict[str, OperatorActionRecord] = {}
        self.audit_events: dict[str, AuditEventRecord] = {}
        self.incident_watches: dict[str, IncidentWatch] = {}
        self.watch_observations: dict[str, IncidentWatchObservation] = {}
        self.watch_latest_observation: dict[str, str] = {}
        self.watch_latest_successful_observation: dict[str, str] = {}
        self.watch_change_records: dict[str, IncidentWatchChange] = {}
        self.incident_projections: dict[str, IncidentProjectionRecord] = {}
        self.news_observations: dict[str, NewsObservation] = {}
        self.incident_candidate_revisions: dict[str, IncidentCandidate] = {}
        self.provider_attempt_records: dict[str, list[ProviderAttempt]] = {}
        self.web_fetch_states: dict[str, WebFetchState] = {}
        self._web_fetch_audits: dict[str, WebFetchAudit] = {}
