"""Explicit headlines outrank broad index hints without losing retained work."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
WEAK = NewsFeedItem(
    "index",
    "Daily",
    "Storm recovery update",
    "https://weak.example/story",
    None,
    None,
    discovery_hint="flood; death-related index theme (unverified)",
)
EXPLICIT = replace(
    WEAK,
    external_id="headline",
    canonical_url="https://explicit.example/story",
    title="Flood kills two people",
    discovery_hint=None,
)


async def prepare(path):
    journal = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
    partition = CollectionPartition("controlled", "flood", NOW - timedelta(days=1), NOW)
    await journal.attach(run, (partition,), now=NOW, budget=10)
    return journal, run


@pytest.mark.parametrize("legacy", [False, True])
async def test_explicit_headline_precedes_earlier_index_tag_without_dropping_either(
    tmp_path, legacy
):
    path = tmp_path / "journal.sqlite"
    journal, _ = await prepare(path)
    work = await journal.claim("search", "index", now=NOW)
    await journal.commit_page(work, CollectionPage(leads=(WEAK, EXPLICIT)), now=NOW)
    if legacy:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE work SET priority=1 WHERE kind='retrieve'")
            db.execute("PRAGMA user_version=1")
        journal = SQLiteCollectionJournal(path)
    first = await journal.claim("retrieve", "first", now=NOW)
    second = await journal.claim("retrieve", "second", now=NOW)
    assert first.lead == EXPLICIT
    assert second.lead == WEAK


async def test_richer_same_generation_rediscovery_upgrades_pending_payload_and_order(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    journal, run = await prepare(path)
    placeholder = replace(EXPLICIT, title="Article title unavailable")
    first = await journal.claim("search", "index", now=NOW)
    await journal.commit_page(
        first, CollectionPage(leads=(WEAK, placeholder), next_cursor="next"), now=NOW
    )
    next_page = await journal.claim("search", "rss", now=NOW)
    await journal.commit_page(next_page, CollectionPage(leads=(EXPLICIT,)), now=NOW)
    retrieved = await journal.claim("retrieve", "reader", now=NOW)
    assert retrieved.lead == EXPLICIT
    snapshot = await journal.snapshot(run.scan_id, now=NOW)
    assert len(snapshot.leads) == 2
    assert snapshot.progress.pages_acquired == 2
    assert snapshot.progress.articles_pending == 2


@pytest.mark.parametrize("legacy", [False, True])
async def test_rediscovery_preserves_refusal_deadline_attempts_and_host_cooldown(
    tmp_path,
    legacy,
):
    path = tmp_path / "journal.sqlite"
    journal, _ = await prepare(path)
    placeholder = replace(EXPLICIT, title="Article title unavailable")
    first = await journal.claim("search", "index", now=NOW)
    await journal.commit_page(
        first, CollectionPage(leads=(placeholder,), next_cursor="next"), now=NOW
    )
    reading = await journal.claim("retrieve", "old", now=NOW)
    retry = NOW + timedelta(seconds=60)
    await journal.fail(
        reading,
        outcome="rate_limited",
        detail="Publisher refusal",
        now=NOW,
        retry_at=retry,
    )
    next_page = await journal.claim("search", "rss", now=NOW)
    await journal.commit_page(next_page, CollectionPage(leads=(EXPLICIT,)), now=NOW)
    if legacy:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE work SET priority=1 WHERE kind='retrieve'")
            db.execute("PRAGMA user_version=1")
    journal = SQLiteCollectionJournal(path)
    assert await journal.claim("retrieve", "too-early", now=NOW) is None
    assert (await journal.next_retry(now=NOW)) == retry
    resumed = await journal.claim("retrieve", "retry", now=retry)
    assert resumed.lead == EXPLICIT
    assert resumed.attempts == 2
    assert resumed.token != reading.token


async def test_weaker_rediscovery_does_not_replace_an_explicit_headline(tmp_path):
    journal, _ = await prepare(tmp_path / "journal.sqlite")
    first = await journal.claim("search", "rss", now=NOW)
    await journal.commit_page(
        first, CollectionPage(leads=(EXPLICIT,), next_cursor="next"), now=NOW
    )
    next_page = await journal.claim("search", "index", now=NOW)
    await journal.commit_page(
        next_page,
        CollectionPage(leads=(replace(EXPLICIT, title="Flood update"),)),
        now=NOW,
    )
    assert (await journal.claim("retrieve", "reader", now=NOW)).lead == EXPLICIT


@pytest.mark.parametrize("completed", [False, True])
async def test_richer_rediscovery_does_not_reset_an_active_lease_or_completed_work(
    tmp_path, completed
):
    journal, run = await prepare(tmp_path / "journal.sqlite")
    first = await journal.claim("search", "index", now=NOW)
    placeholder = replace(EXPLICIT, title="Article title unavailable")
    await journal.commit_page(
        first, CollectionPage(leads=(placeholder,), next_cursor="next"), now=NOW
    )
    reading = await journal.claim("retrieve", "old", now=NOW)
    article = DiscoveryArticle(
        SourceReference(
            "news",
            "Daily",
            "Flood kills two people",
            EXPLICIT.canonical_url,
            NOW,
            None,
            NOW,
        ),
        "Police said two people died in the flood.",
    )
    if completed:
        assert await journal.commit_article(reading, article, now=NOW)
    next_page = await journal.claim("search", "rss", now=NOW)
    await journal.commit_page(next_page, CollectionPage(leads=(EXPLICIT,)), now=NOW)
    assert await journal.claim("retrieve", "duplicate", now=NOW) is None
    if not completed:
        assert await journal.commit_article(reading, article, now=NOW)
    snapshot = await journal.snapshot(run.scan_id, now=NOW)
    assert snapshot.articles == (article,)
    assert snapshot.progress.articles_pending == 0
    assert snapshot.progress.articles_retrieved == 1
