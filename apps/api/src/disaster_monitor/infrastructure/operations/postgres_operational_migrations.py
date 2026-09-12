"""PostgreSQL operational-schema migration persistence."""

from pathlib import Path

from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresOperationalMigrationRepository(PostgresRepositoryBase):
    """Apply the ordered operational migrations on one connection."""

    async def migrate(self, migrations_root: Path | None = None) -> None:
        root = migrations_root or Path(__file__).with_name("migrations")
        scripts = sorted(root.glob("*.sql"))
        if not scripts:
            raise RuntimeError("No operational database migrations were found.")
        async with await self._connection() as connection:
            for path in scripts:
                version = path.stem
                async with connection.cursor() as cursor:
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_migration (
                            version text PRIMARY KEY,
                            applied_at timestamptz NOT NULL DEFAULT now()
                        )
                        """
                    )
                    await cursor.execute(
                        "SELECT 1 FROM schema_migration WHERE version = %s", (version,)
                    )
                    if await cursor.fetchone() is not None:
                        continue
                    await cursor.execute(path.read_text(encoding="utf-8"))
                    await cursor.execute(
                        "INSERT INTO schema_migration(version) VALUES (%s)", (version,)
                    )
