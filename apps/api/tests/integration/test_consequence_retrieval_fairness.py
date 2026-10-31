"""Consequence reporting gets bounded opportunities within the shared request cap."""

import asyncio
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

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def article_lead(index: int, *, consequence: bool) -> NewsFeedItem:
    title = (
        "Flood survivors rebuild their homes"
        if consequence
        else "Flood killed two residents"
    )
    return NewsFeedItem(
        str(index),
        "Regional News",
        title,
        f"https://publisher{index}.example/report",
        NOW,
        None,
        NOW,
    )


async def prepare(path, *, fatal=24, consequence=5, budget=5, consequence_host=None):
    store = SQLiteCollectionJournal(path, lease_seconds=300)
    partition = CollectionPartition("news", "flood", NOW - timedelta(days=1), NOW)
    for _ in range(2):
        run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
        await store.attach(run, (partition,), now=NOW, budget=budget)
    search = await store.claim("search", "searcher", now=NOW)
    leads = tuple(article_lead(i, consequence=False) for i in range(fatal)) + tuple(
        article_lead(100 + i, consequence=True) for i in range(consequence)
    )
    if consequence_host is not None:
        leads = tuple(
            replace(item, canonical_url=f"https://{consequence_host}/consequence")
            if item.title.startswith("Flood survivors")
            else item
            for item in leads
        )
    assert await store.commit_page(search, CollectionPage(leads=leads), now=NOW)
    return store


def is_consequence(work):
    return work.lead.title.startswith("Flood survivors")


async def test_shared_budget_preserves_consequence_opportunities_across_restart(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    store = await prepare(path)
    claimed = [await store.claim("retrieve", str(i), now=NOW) for i in range(4)]
    assert all(not is_consequence(work) for work in claimed)
    store = SQLiteCollectionJournal(path, lease_seconds=300)
    claimed.extend(
        [await store.claim("retrieve", str(i), now=NOW) for i in range(4, 20)]
    )
    assert all(claimed)
    assert all(is_consequence(claimed[i]) for i in (4, 9, 14, 19))
    assert sum(is_consequence(work) for work in claimed) == 4
    assert len({work.work_id for work in claimed}) == 20
    assert await store.claim("retrieve", "over-budget", now=NOW) is None


@pytest.mark.parametrize("consequence", [0, 24])
async def test_empty_priority_lane_does_not_waste_shared_allowance(
    tmp_path, consequence
):
    store = await prepare(
        tmp_path / "journal.sqlite",
        fatal=24 if not consequence else 0,
        consequence=consequence,
    )
    claimed = [await store.claim("retrieve", str(i), now=NOW) for i in range(20)]
    assert all(claimed)
    assert len({work.work_id for work in claimed}) == 20
    assert await store.claim("retrieve", "over-budget", now=NOW) is None


async def test_due_time_still_applies_when_consequence_opportunity_is_due(tmp_path):
    store = await prepare(tmp_path / "journal.sqlite", consequence=1, budget=3)
    first = [await store.claim("retrieve", str(i), now=NOW) for i in range(5)]
    assert is_consequence(first[-1])
    await store.fail(
        first[-1],
        outcome="transport_failed",
        detail="Temporary publisher failure",
        now=NOW,
        retry_at=NOW + timedelta(seconds=60),
    )
    later = [await store.claim("retrieve", str(i), now=NOW) for i in range(5, 12)]
    assert all(later)
    assert all(not is_consequence(work) for work in later)
    assert await store.claim("retrieve", "over-budget", now=NOW) is None


async def test_concurrent_claims_share_one_fairness_position_and_exclusive_leases(
    tmp_path,
):
    store = await prepare(tmp_path / "journal.sqlite", budget=3)
    claimed = await asyncio.gather(
        *(store.claim("retrieve", str(i), now=NOW) for i in range(12))
    )
    assert all(claimed)
    assert len({work.work_id for work in claimed}) == 12
    assert sum(is_consequence(work) for work in claimed) == 2
    assert await store.claim("retrieve", "over-budget", now=NOW) is None


async def test_short_passes_do_not_reset_away_the_consequence_opportunity(tmp_path):
    path = tmp_path / "journal.sqlite"
    store = await prepare(path, consequence=1, budget=1)
    first = [await store.claim("retrieve", str(i), now=NOW) for i in range(4)]
    assert all(not is_consequence(work) for work in first)
    assert await store.claim("retrieve", "over-budget", now=NOW) is None
    scan_id = (await store.active_scans())[0]
    await store.finish_pass(now=NOW)
    store = SQLiteCollectionJournal(path, lease_seconds=300)
    await store.continue_scan(scan_id, now=NOW, budget=1)
    assert is_consequence(await store.claim("retrieve", "resumed", now=NOW))


@pytest.mark.parametrize("blocked_by", ["lease", "cooldown"])
async def test_preferred_lane_respects_publisher_host_access_limits(
    tmp_path, blocked_by
):
    store = await prepare(
        tmp_path / "journal.sqlite",
        consequence=1,
        consequence_host="publisher0.example",
    )
    first = await store.claim("retrieve", "first", now=NOW)
    assert not is_consequence(first)
    if blocked_by == "cooldown":
        await store.fail(
            first,
            outcome="rate_limited",
            detail="Publisher requested a pause",
            now=NOW,
            retry_at=NOW + timedelta(seconds=60),
        )
    later = [await store.claim("retrieve", str(i), now=NOW) for i in range(1, 10)]
    assert all(later)
    assert all(not is_consequence(work) for work in later)
