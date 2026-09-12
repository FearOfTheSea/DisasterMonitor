"""Stable aggregate for cohesive PostgreSQL ingestion persistence components."""

from .postgres_incident_projection_repository import (
    PostgresIncidentProjectionRepository,
)
from .postgres_ingestion_evidence import (
    PostgresIngestionEvidenceRepository,
)
from .postgres_ingestion_jobs import (
    PostgresIngestionJobRepository,
)
from .postgres_operational_migrations import (
    PostgresOperationalMigrationRepository,
)
from .postgres_operator_audit_repository import (
    PostgresOperatorAuditRepository,
)
from .postgres_provider_status_repository import (
    PostgresProviderStatusRepository,
)


class PostgresIngestionRepository(
    PostgresOperationalMigrationRepository,
    PostgresIngestionJobRepository,
    PostgresIngestionEvidenceRepository,
    PostgresProviderStatusRepository,
    PostgresOperatorAuditRepository,
    PostgresIncidentProjectionRepository,
):
    """Compose the operational ports without owning their SQL implementations."""

    durable = True

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty.")
        self._dsn = dsn
