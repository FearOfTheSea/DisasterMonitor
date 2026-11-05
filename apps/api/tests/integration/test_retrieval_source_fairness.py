"""Late metadata producers receive retrieval turns without changing priority caps."""

import asyncio
from collections import Counter
from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 11, 4, tzinfo=UTC)


def lead(source, index, *, weak=False):
    return NewsFeedItem(
        f"{source}-{index}",
        "Daily",
        "Regional bulletin" if weak else "Flood killed two residents",
        f"https://{source}-{index}.example/report",
        None,
        None,
        NOW,
    )


async def prepared(path, *, weak=False):
    interval = ReportingInterval.at_start(30, NOW)
    roots = tuple(
        CollectionPartition(p, "hazard reporting", interval.start, NOW)
        for p in ("early", "late")
    )
    store = SQLiteCollectionJournal(path, lease_seconds=300)
    await store.attach(DiscoveryRun("scan", interval), roots, now=NOW, budget=20)
    first = await store.claim("search", "index", now=NOW, provider="early")
    await store.commit_page(
        first,
        CollectionPage(leads=tuple(lead("early", i, weak=weak) for i in range(200))),
        now=NOW,
    )
    # The second provider arrives after the first has already begun retrieval.
    initial = [await store.claim("retrieve", "initial", now=NOW) for _ in range(8)]
    assert all(w.lead.publisher == "Daily" for w in initial)
    second = await store.claim("search", "index", now=NOW, provider="late")
    await store.commit_page(
        second,
        CollectionPage(leads=tuple(lead("late", i, weak=weak) for i in range(20))),
        now=NOW,
    )
    return store


@pytest.mark.parametrize("weak", [False, True])
async def test_late_source_is_inspected_under_a_sustained_equal_priority_backlog(
    tmp_path, weak
):
    store = await prepared(tmp_path / "journal.sqlite", weak=weak)
    claimed = [await store.claim("retrieve", str(i), now=NOW) for i in range(32)]
    counts = Counter(w.lead.external_id.split("-")[0] for w in claimed)
    assert counts == {"late": 16, "early": 16}
    assert all(w.lead.published_at is None for w in claimed)


async def test_reopening_and_concurrent_claims_preserve_source_turns_and_cap(tmp_path):
    path = tmp_path / "journal.sqlite"
    await prepared(path)
    claimed = []
    for _allocation in range(9):
        store = SQLiteCollectionJournal(path, lease_seconds=300)
        claimed.extend(
            await asyncio.gather(
                *(store.claim("retrieve", str(j), now=NOW) for j in range(8))
            )
        )
    assert all(claimed)
    assert len({w.work_id for w in claimed}) == 72
    assert sum(w.lead.external_id.startswith("late-") for w in claimed) == 20
    assert await store.claim("retrieve", "over-cap", now=NOW) is None


async def test_legacy_upgrade_preserves_work_leases_and_observed_source_links(tmp_path):
    import sqlite3

    path = tmp_path / "journal.sqlite"
    await prepared(path)
    with sqlite3.connect(path) as db:
        before = db.execute(
            "SELECT id,state,token,attempts FROM work ORDER BY id"
        ).fetchall()
        db.executescript(
            "DROP TABLE retrieval_sources; DROP TABLE retrieval_source_rotation;"
        )
    store = SQLiteCollectionJournal(path, lease_seconds=300)
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT id,state,token,attempts FROM work ORDER BY id"
            ).fetchall()
            == before
        )
    claimed = [await store.claim("retrieve", str(i), now=NOW) for i in range(32)]
    assert sum(w.lead.external_id.startswith("late-") for w in claimed) >= 12


async def test_a_delayed_source_does_not_waste_ready_retrieval_turns(tmp_path):
    import sqlite3

    path = tmp_path / "journal.sqlite"
    store = await prepared(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE work SET due=? "
            "WHERE json_extract(payload,'$.external_id') LIKE 'late-%'",
            (NOW.timestamp() + 60,),
        )
    claimed = [await store.claim("retrieve", str(i), now=NOW) for i in range(32)]
    assert all(w.lead.external_id.startswith("early-") for w in claimed)
    assert len({w.work_id for w in claimed}) == 32


async def test_shared_url_keeps_both_producers_but_is_leased_only_once(tmp_path):
    interval = ReportingInterval.at_start(30, NOW)
    store = SQLiteCollectionJournal(tmp_path / "journal.sqlite", lease_seconds=300)
    roots = tuple(
        CollectionPartition(p, "reporting", interval.start, NOW) for p in ("one", "two")
    )
    await store.attach(DiscoveryRun("scan", interval), roots, now=NOW, budget=3)
    shared = lead("shared", 1)
    for provider in ("one", "two"):
        search = await store.claim("search", "index", now=NOW, provider=provider)
        await store.commit_page(
            search, CollectionPage(leads=(shared, lead(provider, 1))), now=NOW
        )
    claimed = await asyncio.gather(
        *(store.claim("retrieve", str(i), now=NOW) for i in range(3))
    )
    assert len({w.work_id for w in claimed}) == 3
    assert sum(w.lead == shared for w in claimed) == 1
    assert await store.claim("retrieve", "empty", now=NOW) is None


async def test_concurrent_legacy_opens_preserve_work_and_upgrade_once(tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "journal.sqlite"
    await prepared(path)
    with sqlite3.connect(path) as db:
        before = db.execute(
            "SELECT id,state,token,attempts FROM work ORDER BY id"
        ).fetchall()
        db.executescript(
            "DROP TABLE retrieval_sources; DROP TABLE retrieval_source_rotation;"
        )
    barrier = Barrier(8)

    def opened(_index):
        barrier.wait()
        return SQLiteCollectionJournal(path, lease_seconds=300)

    with ThreadPoolExecutor(max_workers=8) as pool:
        stores = list(pool.map(opened, range(8)))
    assert len(stores) == 8
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT id,state,token,attempts FROM work ORDER BY id"
            ).fetchall()
            == before
        )
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
