"""Successful evidence and its bounded followup survive together across restart."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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

NOW = datetime(2026, 10, 22, tzinfo=UTC)
LEAD = NewsFeedItem(
    "lead",
    "Daily",
    "Earthquake damage",
    "https://daily.example/story",
    None,
    None,
    discovery_hint="One person killed in an earthquake.",
    search_title="Terremoto deja una persona fallecida y casas dañadas",
)
ARTICLE = DiscoveryArticle(
    SourceReference(
        "news", "Daily", "Earthquake damage", LEAD.canonical_url, NOW, None, NOW
    ),
    "An earthquake struck Lakeview. Fifteen homes were damaged.",
)


def part(query="earthquake", alternate_for=None):
    return CollectionPartition(
        "test-index",
        query,
        NOW - timedelta(days=1),
        NOW,
        generation="test-followup",
        alternate_for=alternate_for,
    )


async def test_successful_article_and_followup_remain_available_after_restart(tmp_path):
    store = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, NOW))
    await store.attach(run, (part(),), now=NOW, budget=1)
    seed = await store.claim("search", "seed", now=NOW)
    assert await store.commit_page(seed, CollectionPage(leads=(LEAD,)), now=NOW)
    work = await store.claim("retrieve", "publisher", now=NOW)
    followup = part("earthquake Lakeview", LEAD.canonical_url)
    assert await store.commit_article(work, ARTICLE, now=NOW, alternates=(followup,))
    await store.finish_pass(now=NOW)
    restarted = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    saved = await restarted.snapshot(run.scan_id, now=NOW)
    assert saved.articles == (ARTICLE,)
    assert saved.leads == (LEAD,)
    assert saved.progress.articles_retrieved == 1
    assert saved.progress.articles_unavailable == 0
    assert saved.progress.searches_pending == 1
    assert not await restarted.commit_article(
        work,
        ARTICLE,
        now=NOW,
        alternates=(part("stale worker phantom", LEAD.canonical_url),),
    )
    assert (
        await restarted.snapshot(run.scan_id, now=NOW)
    ).progress.searches_pending == 1
    await restarted.continue_scan(run.scan_id, now=NOW, budget=1)
    alternate = await restarted.claim("search", "alternate", now=NOW)
    assert alternate.partition == followup


async def test_targeted_fatality_search_precedes_generic_backlog_without_removing_it(
    tmp_path,
):
    from dataclasses import replace

    store = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, NOW))
    generic = part("drought")
    await store.attach(run, (part(), generic), now=NOW, budget=1)
    seed = await store.claim("search", "seed", now=NOW)
    await store.commit_page(seed, CollectionPage(leads=(LEAD,)), now=NOW)
    publisher = await store.claim("retrieve", "publisher", now=NOW)
    targeted = replace(part(LEAD.search_title, LEAD.canonical_url), priority=1)
    await store.commit_article(publisher, ARTICLE, now=NOW, alternates=(targeted,))
    await store.finish_pass(now=NOW)
    restarted = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    await restarted.continue_scan(run.scan_id, now=NOW, budget=1)
    next_search = await restarted.claim("search", "next", now=NOW)
    assert next_search.partition == targeted
    await restarted.commit_page(next_search, CollectionPage(), now=NOW)
    assert (
        await restarted.snapshot(run.scan_id, now=NOW)
    ).progress.searches_pending == 1
    await restarted.finish_pass(now=NOW)
    await restarted.continue_scan(run.scan_id, now=NOW, budget=1)
    assert (await restarted.claim("search", "generic", now=NOW)).partition == generic
