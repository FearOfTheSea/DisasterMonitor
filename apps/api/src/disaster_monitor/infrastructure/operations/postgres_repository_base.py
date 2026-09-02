"""Shared PostgreSQL connection behavior for operational repositories."""

from typing import Any

import psycopg


class PostgresRepositoryBase:
    _dsn: str

    async def _connection(self) -> psycopg.AsyncConnection[Any]:
        return await psycopg.AsyncConnection.connect(self._dsn)
