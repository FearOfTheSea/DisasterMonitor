"""Continuation bookkeeping stays bounded as completed work accumulates."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from disaster_monitor.domain.collection import CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 27, tzinfo=UTC)
PARTITION = TypeAdapter(CollectionPartition)


class WorkMeasuredJournal(SQLiteCollectionJournal):
    """Measure SQLite VM work without a machine-dependent wall-clock limit."""

    def __init__(self, path: Path) -> None:
        self.maximum_steps: int | None = None
        self.steps = 0
        super().__init__(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with super()._connect() as db:
            if self.maximum_steps is not None:

                def progress() -> int:
                    self.steps += 1000
                    return int(
                        self.maximum_steps is not None
                        and self.steps > self.maximum_steps
                    )

                db.set_progress_handler(progress, 1000)
            yield db


def completed_history(size: int):
    for index in range(size):
        partition = CollectionPartition(
            "historical-index",
            f"completed query {index}",
            NOW - timedelta(days=30),
            NOW - timedelta(days=29),
        )
        yield (
            partition.key,
            PARTITION.dump_json(partition),
            index + 1000,
        )


@pytest.mark.parametrize("restart", [False, True])
async def test_continuation_does_not_rescan_completed_history_per_partition(
    tmp_path, restart
):
    path = tmp_path / "collection.sqlite"
    journal = WorkMeasuredJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, NOW))
    partitions = tuple(
        CollectionPartition(
            "current-index", f"query {index}", NOW - timedelta(days=7), NOW
        )
        for index in range(50)
    )
    await journal.attach(run, partitions, now=NOW, budget=10)
    await journal.finish_pass(now=NOW)
    with sqlite3.connect(path) as db:
        db.executemany(
            "INSERT INTO work(id,kind,provider,payload,state,sequence) "
            "VALUES(?,'search','historical-index',?,'done',?)",
            completed_history(12_000),
        )
        sequences_before = dict(db.execute("SELECT id,sequence FROM work"))
        if restart:
            db.execute("DROP INDEX IF EXISTS work_sequence")
    if restart:
        journal = WorkMeasuredJournal(path)
    added = CollectionPartition(
        "current-index", "new query", NOW - timedelta(days=7), NOW
    )

    # Permit ledger-wide control updates, but not one complete history traversal
    # for each of the 51 partitions. VM instructions avoid timing flakiness.
    journal.maximum_steps = 250_000
    await journal.continue_scan(
        run.scan_id, now=NOW, budget=10, partitions=(*partitions, added)
    )
    journal.maximum_steps = None

    assert journal.steps <= 250_000
    with sqlite3.connect(path) as db:
        sequences_after = dict(db.execute("SELECT id,sequence FROM work"))
        assert len(sequences_after) == len(sequences_before) + 1
        assert all(
            sequences_after[key] == value for key, value in sequences_before.items()
        )
        assert sequences_after[added.key] == max(sequences_before.values()) + 1
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    assert (await journal.read(run.scan_id)).status == "running"


async def test_full_preexisting_journal_keeps_retained_views_accessible(tmp_path):
    path = tmp_path / "collection.sqlite"
    limit = 1024 * 1024
    journal = SQLiteCollectionJournal(path, maximum_bytes=limit)
    run = replace(
        DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, NOW)),
        issues=("Retained reporting remains inspectable.",),
    )
    await journal.save(run)
    with sqlite3.connect(path) as db:
        db.execute("DROP INDEX IF EXISTS work_sequence")
        db.execute("CREATE TABLE existing_payloads(payload BLOB)")
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        db.execute(f"PRAGMA max_page_count={limit // page_size}")
        while True:
            try:
                db.execute("INSERT INTO existing_payloads VALUES(zeroblob(3500))")
                db.commit()
            except sqlite3.Error as error:
                db.rollback()
                assert error.sqlite_errorcode == sqlite3.SQLITE_FULL
                break
    restarted = SQLiteCollectionJournal(path, maximum_bytes=limit)
    assert await restarted.read(run.scan_id) == run
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    expanded = SQLiteCollectionJournal(path, maximum_bytes=4 * limit)
    partition = CollectionPartition(
        "current-index", "flood", NOW - timedelta(days=7), NOW
    )
    await expanded.continue_scan(
        run.scan_id, now=NOW, budget=1, partitions=(partition,)
    )
    work = await expanded.claim("search", "worker", now=NOW)
    assert work is not None and work.partition is not None
    assert work.partition.key == partition.key
    assert (await expanded.read(run.scan_id)).issues == run.issues
