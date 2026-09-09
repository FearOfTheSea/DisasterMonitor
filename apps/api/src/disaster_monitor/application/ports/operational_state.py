"""Aggregate contract for composition; consumers use capability-specific ports."""

from typing import Protocol

from disaster_monitor.application.ports.evidence_store import EvidenceWriter
from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionStore,
)
from disaster_monitor.application.ports.ingest_jobs import (
    IngestJobQueue,
    JobStatusReader,
)
from disaster_monitor.application.ports.news import NewsCandidateStore
from disaster_monitor.application.ports.operator_actions import OperatorActionStore
from disaster_monitor.application.ports.provider_status import (
    ProviderAttemptWriter,
    ProviderStatusReader,
)
from disaster_monitor.application.ports.snapshots import (
    ImmutableBlobStore as ImmutableBlobStore,
)
from disaster_monitor.application.ports.snapshots import (
    SnapshotRetentionStore,
    SnapshotWriter,
)


class OperationalRepository(
    IngestJobQueue,
    JobStatusReader,
    SnapshotWriter,
    SnapshotRetentionStore,
    EvidenceWriter,
    OperatorActionStore,
    ProviderStatusReader,
    ProviderAttemptWriter,
    IncidentProjectionStore,
    NewsCandidateStore,
    Protocol,
):
    """Complete persistence surface used only to assemble the runtime."""

    @property
    def durable(self) -> bool: ...


class MonitoringReadinessReader(IncidentProjectionStore, Protocol):
    """Narrow read surface used to report monitoring topology."""

    @property
    def durable(self) -> bool: ...
