"""Atomic publisher access leases and bounded robots caching beside collection work."""

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from math import isfinite
from pathlib import Path
from uuid import uuid4

from disaster_monitor.infrastructure.news.public_document_access import (
    PublicAccessReservation,
    PublicRedirectResume,
)


class SQLitePublicDocumentAccess:
    def __init__(self, path: Path, *, cache_entries: int = 256) -> None:
        if cache_entries < 1:
            raise ValueError("Publisher policy cache needs a positive capacity.")
        self._path = path
        self._cache_entries = cache_entries
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS publisher_access (
                host TEXT PRIMARY KEY, robots TEXT, policy_at REAL,
                interval REAL NOT NULL DEFAULT 0, requested REAL NOT NULL DEFAULT 0,
                token TEXT, lease_until REAL NOT NULL DEFAULT 0
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS publisher_redirects (
                url TEXT PRIMARY KEY, destination TEXT NOT NULL,
                visited TEXT NOT NULL, observed REAL NOT NULL
            )""")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    async def robots(self, host: str, *, now: float) -> str | None:
        return await asyncio.to_thread(self._robots, host, now)

    def _robots(self, host: str, now: float) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT robots,policy_at FROM publisher_access WHERE host=?", (host,)
            ).fetchone()
            if row and row["robots"] is not None and 0 <= now - row["policy_at"] < 3600:
                return str(row["robots"])
        return None

    async def remember_robots(
        self, host: str, text: str, interval: float, *, now: float
    ) -> None:
        if (
            len(text.encode("utf-8")) > 300_000
            or not isfinite(interval)
            or not 0 <= interval <= 31_536_000
        ):
            raise ValueError("Publisher robots cache record exceeds its boundary.")
        await asyncio.to_thread(self._remember_robots, host, text, interval, now)

    def _remember_robots(
        self, host: str, text: str, interval: float, now: float
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO publisher_access(host,robots,policy_at,interval) "
                "VALUES(?,?,?,?) ON CONFLICT(host) DO UPDATE SET "
                "robots=excluded.robots,policy_at=excluded.policy_at,"
                "interval=excluded.interval",
                (host, text, now, interval),
            )
            # Evict only text, never timing: expiry or cache pressure must not
            # grant an early request after a restart or policy refresh.
            db.execute(
                "UPDATE publisher_access SET robots=NULL,policy_at=NULL WHERE host IN "
                "(SELECT host FROM publisher_access WHERE robots IS NOT NULL "
                "ORDER BY policy_at DESC,host LIMIT -1 OFFSET ?)",
                (self._cache_entries,),
            )

    async def claim(
        self, host: str, *, now: float, lease_seconds: float
    ) -> PublicAccessReservation:
        return await asyncio.to_thread(self._claim, host, now, lease_seconds)

    def _claim(
        self, host: str, now: float, lease_seconds: float
    ) -> PublicAccessReservation:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO publisher_access(host) VALUES(?)", (host,)
            )
            row = db.execute(
                "SELECT * FROM publisher_access WHERE host=?", (host,)
            ).fetchone()
            assert row is not None
            ready = max(row["requested"] + row["interval"], row["lease_until"])
            if ready > now:
                return PublicAccessReservation(None, ready - now)
            token = str(uuid4())
            # Persist the start before network I/O. A crashed request still counts
            # toward publisher timing even when its finish was never observed.
            db.execute(
                "UPDATE publisher_access SET requested=?,token=?,lease_until=? "
                "WHERE host=?",
                (now, token, now + lease_seconds, host),
            )
            return PublicAccessReservation(token)

    async def finish(self, host: str, token: str, *, now: float) -> None:
        await asyncio.to_thread(self._finish, host, token, now)

    def _finish(self, host: str, token: str, now: float) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE publisher_access SET requested=MAX(requested,?),token=NULL,"
                "lease_until=0 WHERE host=? AND token=?",
                (now, host, token),
            )

    async def redirect(self, url: str, *, now: float) -> PublicRedirectResume | None:
        return await asyncio.to_thread(self._redirect, url, now)

    def _redirect(self, url: str, now: float) -> PublicRedirectResume | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM publisher_redirects WHERE url=?", (url,)
            ).fetchone()
            if row and 0 <= now - row["observed"] < 3600:
                return PublicRedirectResume(
                    row["destination"], tuple(json.loads(row["visited"]))
                )
        return None

    async def remember_redirect(
        self, url: str, resume: PublicRedirectResume, *, now: float
    ) -> None:
        if (
            len(url) > 8192
            or len(resume.destination) > 8192
            or not 1 <= len(resume.visited) <= 5
            or any(len(value) != 64 for value in resume.visited)
        ):
            raise ValueError("Publisher redirect continuation exceeds its boundary.")
        await asyncio.to_thread(self._remember_redirect, url, resume, now)

    def _remember_redirect(
        self, url: str, resume: PublicRedirectResume, now: float
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO publisher_redirects VALUES(?,?,?,?) "
                "ON CONFLICT(url) DO UPDATE SET destination=excluded.destination,"
                "visited=excluded.visited,observed=excluded.observed",
                (url, resume.destination, json.dumps(resume.visited), now),
            )
            db.execute(
                "DELETE FROM publisher_redirects WHERE url IN "
                "(SELECT url FROM publisher_redirects ORDER BY observed DESC,url "
                "LIMIT -1 OFFSET ?)",
                (self._cache_entries,),
            )

    async def clear_redirect(self, url: str) -> None:
        await asyncio.to_thread(self._clear_redirect, url)

    def _clear_redirect(self, url: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM publisher_redirects WHERE url=?", (url,))
