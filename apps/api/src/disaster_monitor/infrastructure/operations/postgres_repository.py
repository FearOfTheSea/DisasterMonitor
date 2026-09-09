"""Composed PostgreSQL/PostGIS operational repository."""

from disaster_monitor.infrastructure.operations.postgres_ingestion_repository import (
    PostgresIngestionRepository,
)
from disaster_monitor.infrastructure.operations.postgres_news_repository import (
    PostgresNewsRepository,
)
from disaster_monitor.infrastructure.operations.postgres_watch_repository import (
    PostgresIncidentWatchRepository,
)


class PostgresOperationalRepository(
    PostgresIngestionRepository,
    PostgresIncidentWatchRepository,
    PostgresNewsRepository,
):
    """Implement the complete operational port from cohesive repositories."""
