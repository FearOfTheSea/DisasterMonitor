"""Revision5 work adopts new regional ranking without repeating acquisition."""

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 30, tzinfo=UTC)


@pytest.mark.parametrize("state", ["pending", "leased", "capacity"])
@pytest.mark.parametrize(
    ("title", "expected_priority"),
    [
        ("Un éboulement meurtrier de la falaise", 3),
        ("Deprem için anma programı düzenlendi", 2),
    ],
)
async def test_revision5_retained_work_adopts_new_policy_without_changing_its_state(
    tmp_path, state, title, expected_priority
):
    path = tmp_path / "collection.sqlite"
    store = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, NOW))
    root = CollectionPartition("controlled", "earthquake", NOW - timedelta(days=7), NOW)
    lead = NewsFeedItem(
        "regional", "Local paper", title, "https://local.example/report", None, None
    )
    await store.attach(run, (root,), now=NOW, budget=10)
    search = await store.claim("search", "index", now=NOW)
    assert search is not None
    await store.commit_page(
        search, CollectionPage(leads=(lead,), next_cursor="retained-cursor"), now=NOW
    )
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        # Exact predecessor revision and its old result, not an artificially
        # older schema that already passed the revision5 migration tests.
        db.execute("PRAGMA user_version=5")
        db.execute(
            "UPDATE work SET priority=0,state=?,attempts=2,token='retained-token',"
            "lease_until=?,due=?,outcome='rate_limited' WHERE kind='retrieve'",
            (state, NOW.timestamp() + 60, NOW.timestamp() + 30),
        )
        before = dict(db.execute("SELECT * FROM work WHERE kind='retrieve'").fetchone())
        unchanged = {
            table: [tuple(row) for row in db.execute("SELECT * FROM " + table)]
            for table in (
                "attempts",
                "pages",
                "leads",
                "evidence",
                "scans",
                "passes",
                "pass_budget",
                "scan_work",
                "work_links",
                "retrieval_rotation",
            )
        }
    restarted = SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        after = dict(db.execute("SELECT * FROM work WHERE kind='retrieve'").fetchone())
        assert after.pop("priority") == expected_priority
        before.pop("priority")
        assert after == before
        for table, rows in unchanged.items():
            assert [tuple(row) for row in db.execute("SELECT * FROM " + table)] == rows
    assert await restarted.read(run.scan_id) == await store.read(run.scan_id)
    # A second open must not change work, refill budgets or create attempts.
    SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        again = dict(db.execute("SELECT * FROM work WHERE kind='retrieve'").fetchone())
        assert again.pop("priority") == expected_priority
        assert again == before
        for table, rows in unchanged.items():
            assert [tuple(row) for row in db.execute("SELECT * FROM " + table)] == rows
