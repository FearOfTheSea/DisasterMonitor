"""SQLite page admission budget with reserved space for durable stop metadata."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from disaster_monitor.application.ports.discovery import DiscoveryCapacityError


@dataclass(frozen=True)
class CollectionStorageBudget:
    path: Path
    maximum_bytes: int

    def __post_init__(self) -> None:
        if self.maximum_bytes < 1024 * 1024:
            raise ValueError("Discovery storage budget must be at least one MiB.")

    def configure(self, db: sqlite3.Connection) -> None:
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        # SQLite preserves an existing database larger than a newly lowered limit.
        # Admission checks refuse growth; no retained rows are deleted to fit it.
        db.execute(f"PRAGMA max_page_count={self.maximum_bytes // page_size}")
        db.execute(f"PRAGMA journal_size_limit={self.maximum_bytes}")
        db.execute("PRAGMA wal_autocheckpoint=128")

    def check_admission(self, db: sqlite3.Connection) -> None:
        pages = db.execute("PRAGMA page_count").fetchone()[0]
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        reserve = min(8 * 1024 * 1024, self.maximum_bytes // 8)
        if pages * page_size > self.maximum_bytes - reserve:
            raise DiscoveryCapacityError()
        # A long-lived reader can prevent checkpoints. Stop admitting writes rather
        # than allowing its WAL to grow without a bound. A single transaction can
        # add at most the configured database page budget before this next check.
        try:
            wal_bytes = Path(str(self.path) + "-wal").stat().st_size
        except FileNotFoundError:
            wal_bytes = 0
        if wal_bytes >= self.maximum_bytes:
            raise DiscoveryCapacityError()


def is_storage_full(error: sqlite3.Error) -> bool:
    return getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL
