"""Ranking upgrades preserve durable work and older search scheduling migrations."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)
WEAK = NewsFeedItem(
    "weak",
    "Daily",
    "Recovery update",
    "https://daily.example/weak",
    None,
    None,
    discovery_hint="flood; death-related index theme (unverified)",
)
SPECIFIC = replace(
    WEAK,
    canonical_url="https://specific.example/story",
    discovery_hint="Two died in the flood.",
)
HEADLINE = replace(
    WEAK,
    canonical_url="https://headline.example/story",
    title="Flood killed two people",
    discovery_hint=None,
)


@pytest.mark.parametrize("version", [0, 1, 2, 3, 4, 5])
@pytest.mark.parametrize("missing_column", [False, True])
async def test_old_journal_upgrades_both_policies_without_resetting_any_work(
    tmp_path, version, missing_column
):
    path = tmp_path / "collection.sqlite"
    store = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
    root = CollectionPartition("controlled", "flood", NOW - timedelta(days=1), NOW)
    followup = replace(root, query="followup", alternate_for=WEAK.canonical_url)
    await store.attach(run, (root,), now=NOW, budget=10)
    search = await store.claim("search", "search", now=NOW)
    await store.commit_page(
        search,
        CollectionPage(leads=(WEAK, SPECIFIC, HEADLINE), next_cursor="retained-cursor"),
        now=NOW,
    )
    await store.attach(
        replace(run, scan_id=str(uuid4())), (followup,), now=NOW, budget=10
    )
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        db.execute("UPDATE work SET priority=1 WHERE kind='retrieve'")
        # Every unfinished state must receive the upgrade; its acquisition state
        # and lease/refusal metadata must survive byte-for-byte.
        for lead, state in (
            (WEAK, "pending"),
            (SPECIFIC, "leased"),
            (HEADLINE, "capacity"),
        ):
            db.execute(
                "UPDATE work SET state=?,attempts=2,token='old-token',"
                "lease_until=?,due=?,outcome='rate_limited' "
                "WHERE json_extract(payload,'$.canonical_url')=?",
                (state, NOW.timestamp() + 60, NOW.timestamp() + 30, lead.canonical_url),
            )
        if version < 3 or missing_column:
            for row in db.execute(
                "SELECT id,payload FROM work WHERE kind='search'"
            ).fetchall():
                payload = json.loads(row["payload"])
                payload["priority"] = int(bool(payload.get("alternate_for")))
                db.execute(
                    "UPDATE work SET priority=?,payload=? WHERE id=?",
                    (payload["priority"], json.dumps(payload), row["id"]),
                )
        if missing_column:
            db.execute("DROP INDEX work_acquisition_order")
            db.execute("ALTER TABLE work DROP COLUMN priority")
        db.execute(f"PRAGMA user_version={version}")
        before = {r["id"]: dict(r) for r in db.execute("SELECT * FROM work")}
        retained = {
            table: [tuple(r) for r in db.execute(f"SELECT * FROM {table}")]
            for table in (
                "attempts",
                "pages",
                "leads",
                "scans",
                "passes",
                "pass_budget",
                "scan_work",
                "work_links",
            )
        }
    SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        after = {r["id"]: dict(r) for r in db.execute("SELECT * FROM work")}
        assert set(after) == set(before)
        for key, old in before.items():
            new = after[key]
            assert {
                k: v for k, v in old.items() if k not in ("priority", "payload")
            } == {k: v for k, v in new.items() if k not in ("priority", "payload")}
            old_payload, new_payload = (
                json.loads(old["payload"]),
                json.loads(new["payload"]),
            )
            assert {k: v for k, v in old_payload.items() if k != "priority"} == {
                k: v for k, v in new_payload.items() if k != "priority"
            }
            if new["kind"] == "search" and new["state"] in (
                "pending",
                "leased",
                "capacity",
            ):
                assert new["priority"] == int(not new_payload.get("alternate_for"))
            elif new["kind"] == "retrieve":
                assert (
                    new["priority"]
                    == {
                        WEAK.canonical_url: 1,
                        SPECIFIC.canonical_url: 2,
                        HEADLINE.canonical_url: 3,
                    }[new_payload["canonical_url"]]
                )
        for table, rows in retained.items():
            assert [tuple(r) for r in db.execute(f"SELECT * FROM {table}")] == rows
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
    # Reopening must be idempotent, including leased and capacity-stopped work.
    SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert {r["id"]: dict(r) for r in db.execute("SELECT * FROM work")} == after


async def test_specific_snippet_is_claimed_between_headline_and_earlier_weak_theme(
    tmp_path,
):
    store = SQLiteCollectionJournal(tmp_path / "collection.sqlite")
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
    root = CollectionPartition("controlled", "flood", NOW - timedelta(days=1), NOW)
    await store.attach(run, (root,), now=NOW, budget=10)
    work = await store.claim("search", "index", now=NOW)
    await store.commit_page(
        work, CollectionPage(leads=(WEAK, SPECIFIC, HEADLINE)), now=NOW
    )
    assert (await store.claim("retrieve", "first", now=NOW)).lead == HEADLINE
    assert (await store.claim("retrieve", "second", now=NOW)).lead == SPECIFIC
    assert (await store.claim("retrieve", "third", now=NOW)).lead == WEAK
