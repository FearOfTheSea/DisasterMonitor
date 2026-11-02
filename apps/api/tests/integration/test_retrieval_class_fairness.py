"""Weak metadata must receive inspection opportunities under sustained strong load."""

import asyncio
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    lead_retrieval_priority,
)
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 11, 1, tzinfo=UTC)


async def prepare(path, *, budget=5):
    store = SQLiteCollectionJournal(path, lease_seconds=300)
    interval = ReportingInterval.at_start(30, NOW)
    partition = CollectionPartition("news", "hazard reporting", interval.start, NOW)
    await store.attach(
        DiscoveryRun("scan", interval), (partition,), now=NOW, budget=budget
    )
    search = await store.claim("search", "index", now=NOW)
    leads = []
    for priority, title, hint in (
        (3, "Flood killed two residents", None),
        (2, "Flood survivors rebuild their homes", None),
        (1, "Regional news", "flood; death-related index theme"),
        (0, "Regional conditions bulletin", None),
    ):
        for index in range(32):
            lead = NewsFeedItem(
                f"{priority}-{index}",
                "Regional News",
                title,
                f"https://class{priority}-{index}.example/report",
                NOW - timedelta(days=20),
                None,
                NOW,
                discovery_hint=hint,
            )
            assert lead_retrieval_priority(lead) == priority
            leads.append(lead)
    assert await store.commit_page(search, CollectionPage(leads=tuple(leads)), now=NOW)
    return store, {lead.canonical_url: lead for lead in leads}


def assert_bounded_coverage(claimed, leads):
    assert all(claimed)
    assert len({work.work_id for work in claimed}) == 20
    counts = Counter(lead_retrieval_priority(work.lead) for work in claimed)
    assert counts == {3: 12, 2: 4, 1: 2, 0: 2}
    # Queue order must not manufacture publication, article text or source facts.
    assert all(work.lead == leads[work.lead.canonical_url] for work in claimed)


async def test_all_ready_classes_receive_turns_without_increasing_request_allowance(
    tmp_path,
):
    store, leads = await prepare(tmp_path / "journal.sqlite")
    claimed = [await store.claim("retrieve", str(i), now=NOW) for i in range(20)]
    assert_bounded_coverage(claimed, leads)
    assert await store.claim("retrieve", "over-budget", now=NOW) is None


async def test_concurrent_workers_share_all_class_opportunities(tmp_path):
    store, leads = await prepare(tmp_path / "journal.sqlite")
    claimed = await asyncio.gather(
        *(store.claim("retrieve", str(i), now=NOW) for i in range(20))
    )
    assert_bounded_coverage(claimed, leads)
    assert await store.claim("retrieve", "over-budget", now=NOW) is None


async def test_short_passes_and_reopen_preserve_weak_class_opportunities(tmp_path):
    path = tmp_path / "journal.sqlite"
    store, leads = await prepare(path, budget=1)
    claimed = []
    for allocation in range(5):
        if allocation:
            await store.finish_pass(now=NOW)
            store = SQLiteCollectionJournal(path, lease_seconds=300)
            await store.continue_scan("scan", now=NOW, budget=1)
        claimed.extend(
            [await store.claim("retrieve", str(i), now=NOW) for i in range(4)]
        )
        assert await store.claim("retrieve", "over-budget", now=NOW) is None
    assert_bounded_coverage(claimed, leads)


@pytest.mark.parametrize("priority", [0, 1])
@pytest.mark.parametrize("unavailable", ["future_due", "live_lease"])
async def test_unready_weak_class_falls_back_without_wasting_requests(
    tmp_path, priority, unavailable
):
    path = tmp_path / "journal.sqlite"
    store, _ = await prepare(path)
    until = (NOW + timedelta(seconds=60)).timestamp()
    with sqlite3.connect(path) as db:
        if unavailable == "future_due":
            db.execute("UPDATE work SET due=? WHERE priority=?", (until, priority))
        else:
            db.execute(
                "UPDATE work SET state='leased',token='other-worker',lease_until=? "
                "WHERE kind='retrieve' AND priority=?",
                (until, priority),
            )
    claimed = [await store.claim("retrieve", str(i), now=NOW) for i in range(20)]
    assert all(claimed)
    assert all(lead_retrieval_priority(work.lead) != priority for work in claimed)
    assert len({work.work_id for work in claimed}) == 20
    assert await store.claim("retrieve", "over-budget", now=NOW) is None
