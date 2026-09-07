"""Aggregate contract for composition; consumers use capability-specific ports."""

from typing import Protocol

from disaster_monitor.application.ports.evidence_store import EvidenceWriter
from disaster_monitor.application.ports.ingest_jobs import (
    IngestJobQueue,
    JobStatusReader,
)
from disaster_monitor.application.ports.operator_actions import OperatorActionStore
from disaster_monitor.application.ports.provider_status import ProviderStatusReader
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
    Protocol,
):
    """Complete persistence surface used only to assemble the runtime."""
