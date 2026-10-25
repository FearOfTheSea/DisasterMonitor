"""Claim traversal preserves scheduling beyond long runs of ineligible work."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 24, tzinfo=UTC)


async def searches(path, count=600, *, budget=1):
    store = SQLiteCollectionJournal(path)
    run = DiscoveryRun("first", ReportingInterval.at_start(1, NOW))
    partitions = tuple(
        CollectionPartition(
            "controlled", f"query {index}", run.interval.start, NOW, priority=1
        )
        for index in range(count)
    )
    ready = CollectionPartition("other", "ready", run.interval.start, NOW, priority=1)
    await store.attach(run, (*partitions, ready), now=NOW, budget=budget)
    with sqlite3.connect(path) as db:
        db.executemany(
            "UPDATE work SET sequence=? WHERE id=?",
            [(i, p.key) for i, p in enumerate((*partitions, ready))],
        )
    return store, run, partitions, ready


async def test_claim_exhausts_many_heads_without_skipping_ready_work_or_budget(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    store, run, partitions, ready = await searches(path)
    await store.attach(
        DiscoveryRun("second", run.interval),
        (*partitions, ready),
        now=NOW,
        budget=1,
    )
    with sqlite3.connect(path) as db:
        db.executemany(
            "UPDATE work SET attempts=4 WHERE id=?", [(p.key,) for p in partitions]
        )
    claimed = await store.claim("search", "worker", now=NOW)
    assert claimed.partition == ready
    assert claimed.attempts == 1
    assert await store.commit_page(claimed, CollectionPage(), now=NOW)
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM work WHERE state='failed' "
            "AND outcome='attempts_exhausted'"
        ).fetchone()[0] == len(partitions)
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert (
            db.execute(
                "SELECT remaining FROM pass_budget WHERE provider='other'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("reason", ["future_due", "live_lease", "cooldown", "budget"])
async def test_many_ineligible_heads_do_not_hide_work_from_another_provider(
    tmp_path, reason
):
    path = tmp_path / "journal.sqlite"
    store, _, partitions, ready = await searches(path)
    until = (NOW + timedelta(seconds=60)).timestamp()
    with sqlite3.connect(path) as db:
        if reason == "future_due":
            db.execute("UPDATE work SET due=? WHERE provider='controlled'", (until,))
        elif reason == "live_lease":
            db.execute(
                "UPDATE work SET state='leased',token='original',lease_until=? "
                "WHERE provider='controlled'",
                (until,),
            )
        elif reason == "cooldown":
            db.execute("INSERT INTO cooldowns VALUES('controlled',?)", (until,))
        else:
            (pass_id,) = db.execute("SELECT id FROM passes WHERE active=1").fetchone()
            db.execute("INSERT INTO pass_budget VALUES(?,'controlled',0)", (pass_id,))
    claimed = await store.claim("search", "worker", now=NOW)
    assert claimed.partition == ready
    assert await store.commit_page(claimed, CollectionPage(), now=NOW)
    assert await store.claim("search", "worker", now=NOW) is None
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM work WHERE provider='controlled' AND attempts=0"
        ).fetchone()[0] == len(partitions)


async def test_publisher_host_lease_does_not_hide_a_later_other_host(tmp_path):
    path = tmp_path / "journal.sqlite"
    store, _, _, _ = await searches(path, count=0, budget=4)
    search = await store.claim("search", "index", now=NOW)
    blocked = tuple(
        NewsFeedItem(
            "controlled",
            "Daily",
            "Flood killed two people",
            f"https://alpha.example/report-{i}",
            None,
            None,
        )
        for i in range(600)
    )
    other = NewsFeedItem(
        "controlled",
        "Daily",
        "A regional report",
        "https://beta.example/report",
        None,
        None,
    )
    assert await store.commit_page(
        search, CollectionPage(leads=(*blocked, other)), now=NOW
    )
    first = await store.claim("retrieve", "one", now=NOW)
    assert first.lead.canonical_url.startswith("https://alpha.example/")
    second = await store.claim("retrieve", "two", now=NOW)
    assert second.lead == other
    assert first.token != second.token
    assert await store.claim("retrieve", "three", now=NOW) is None
