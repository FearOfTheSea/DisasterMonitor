"""Bulk archives leave finite admission space for other discovery routes."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def lead(number):
    return NewsFeedItem(
        str(number),
        "Daily",
        "Flood report",
        f"https://daily.example/{number}",
        None,
        None,
    )


async def setup(path, **options):
    journal = SQLiteCollectionJournal(
        path,
        maximum_leads=5,
        bulk_index_providers=frozenset({"index", "second-index"}),
        reserved_targeted_leads=1,
        **options,
    )
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
    partitions = tuple(
        CollectionPartition(provider, "hazards", NOW - timedelta(days=1), NOW)
        for provider in ("index", "second-index", "targeted")
    )
    await journal.attach(run, partitions, now=NOW, budget=10)
    return journal, run


async def commit(journal, provider, *numbers, next_cursor=None):
    work = await journal.claim("search", "reader", now=NOW, provider=provider)
    assert work is not None
    result = await journal.commit_page(
        work,
        CollectionPage(leads=tuple(lead(n) for n in numbers), next_cursor=next_cursor),
        now=NOW,
    )
    return work, result


async def test_bulk_limit_preserves_cursor_and_other_route_admission(tmp_path):
    journal, run = await setup(tmp_path / "journal.sqlite")
    _, admitted = await commit(journal, "index", 1, 2, 3, 4, next_cursor="retained")
    assert admitted
    rejected, admitted = await commit(
        journal, "index", 5, next_cursor="not-acknowledged"
    )
    assert not admitted
    assert await journal.claim("search", "again", now=NOW, provider="index") is None
    _, admitted = await commit(journal, "targeted", 5, next_cursor="targeted-next")
    assert admitted
    _, admitted = await commit(journal, "targeted", 6)
    assert not admitted  # Reservation never expands the global five-lead limit.
    snapshot = await journal.snapshot(run.scan_id, now=NOW)
    assert {item.canonical_url for item in snapshot.leads} == {
        lead(n).canonical_url for n in range(1, 6)
    }
    assert snapshot.progress.can_continue
    article = await journal.claim("retrieve", "publisher", now=NOW)
    assert article is not None
    assert article.lead.canonical_url == lead(1).canonical_url
    assert rejected.partition.cursor == "retained"


async def test_targeted_rediscovery_releases_bulk_only_space_after_restart(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal, run = await setup(path)
    assert (await commit(journal, "index", 1, 2, 3, 4, next_cursor="retained"))[1]
    assert not (await commit(journal, "index", 5))[1]
    # The shared URL now has a non-archive route; it consumes only one global
    # record and no longer occupies a slot reserved exclusively for bulk work.
    assert (await commit(journal, "targeted", 1))[1]
    await journal.finish_pass(now=NOW)
    restarted = SQLiteCollectionJournal(
        path,
        maximum_leads=5,
        bulk_index_providers=frozenset({"index", "second-index"}),
        reserved_targeted_leads=1,
    )
    await restarted.continue_scan(run.scan_id, now=NOW, budget=10)
    work, admitted = await commit(restarted, "index", 5)
    assert work.partition.cursor == "retained"
    assert admitted
    assert len((await restarted.snapshot(run.scan_id, now=NOW)).leads) == 5


async def test_two_bulk_providers_share_pool_and_duplicate_urls_do_not_expand_it(
    tmp_path,
):
    journal, run = await setup(tmp_path / "journal.sqlite")
    assert (await commit(journal, "index", 1, 2, next_cursor="next"))[1]
    assert (await commit(journal, "second-index", 2, 3, 4, next_cursor="next"))[1]
    assert (await commit(journal, "index", 1, 2))[1]
    assert not (await commit(journal, "second-index", 5))[1]
    assert (await commit(journal, "targeted", 5))[1]
    assert len((await journal.snapshot(run.scan_id, now=NOW)).leads) == 5


async def test_legacy_overfull_pool_keeps_evidence_and_allows_no_growth_pages(tmp_path):
    path = tmp_path / "journal.sqlite"
    legacy = SQLiteCollectionJournal(path, maximum_leads=5)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
    partition = CollectionPartition("index", "hazards", NOW - timedelta(days=1), NOW)
    await legacy.attach(run, (partition,), now=NOW, budget=10)
    assert (await commit(legacy, "index", 1, 2, 3, 4, 5, next_cursor="retained"))[1]
    reserved = SQLiteCollectionJournal(
        path,
        maximum_leads=5,
        bulk_index_providers=frozenset({"index"}),
        reserved_targeted_leads=1,
    )
    assert (
        await commit(reserved, "index", 1, 2, next_cursor="duplicate-acknowledged")
    )[1]
    assert len((await reserved.snapshot(run.scan_id, now=NOW)).leads) == 5


@pytest.mark.parametrize("reserved", [-1, 6, True])
def test_invalid_reservation_is_rejected(tmp_path, reserved):
    with pytest.raises(ValueError, match="reservation"):
        SQLiteCollectionJournal(
            tmp_path / "journal.sqlite",
            maximum_leads=5,
            reserved_targeted_leads=reserved,
        )
