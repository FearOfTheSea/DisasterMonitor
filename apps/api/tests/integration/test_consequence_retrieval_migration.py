"""Consequence ranking upgrades retained unfinished work without changing evidence."""

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
    assess_article,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 27, tzinfo=UTC)
CONSEQUENCE = NewsFeedItem(
    "consequence",
    "Local Daily",
    "Flood survivors discuss long-term rehabilitation",
    "https://daily.example/recovery",
    None,
    None,
)


@pytest.mark.parametrize("state", ["pending", "leased", "capacity"])
async def test_version4_journal_upgrades_consequence_work_without_resetting_state(
    tmp_path, state
):
    path = tmp_path / "collection.sqlite"
    journal = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(14, NOW))
    partition = CollectionPartition(
        "controlled", "flood", NOW - timedelta(days=14), NOW
    )
    await journal.attach(run, (partition,), now=NOW, budget=10)
    search = await journal.claim("search", "index", now=NOW)
    await journal.commit_page(search, CollectionPage(leads=(CONSEQUENCE,)), now=NOW)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        db.execute(
            "UPDATE work SET priority=0,state=?,attempts=2,token='retained-token',"
            "lease_until=?,due=?,outcome='rate_limited' WHERE kind='retrieve'",
            (state, NOW.timestamp() + 60, NOW.timestamp() + 30),
        )
        db.execute("PRAGMA user_version=4")
        before = dict(db.execute("SELECT * FROM work WHERE kind='retrieve'").fetchone())
        attempts = db.execute("SELECT * FROM attempts").fetchall()
    restarted = SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        after = dict(db.execute("SELECT * FROM work WHERE kind='retrieve'").fetchone())
        assert after.pop("priority") == 2
        before.pop("priority")
        assert after == before
        assert db.execute("SELECT * FROM attempts").fetchall() == attempts
    assert await restarted.read(run.scan_id) == await journal.read(run.scan_id)


async def test_consequence_is_claimed_after_direct_death_and_before_weak_theme(
    tmp_path,
):
    journal = SQLiteCollectionJournal(tmp_path / "collection.sqlite")
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(14, NOW))
    partition = CollectionPartition(
        "controlled", "flood", NOW - timedelta(days=14), NOW
    )
    weak = replace(
        CONSEQUENCE,
        title="Recovery update",
        canonical_url="https://weak.example/story",
        discovery_hint="flood; death-related index theme",
    )
    direct = replace(
        CONSEQUENCE,
        title="Flood killed two people",
        canonical_url="https://direct.example/story",
    )
    await journal.attach(run, (partition,), now=NOW, budget=10)
    search = await journal.claim("search", "index", now=NOW)
    await journal.commit_page(
        search, CollectionPage(leads=(weak, CONSEQUENCE, direct)), now=NOW
    )
    assert (await journal.claim("retrieve", "first", now=NOW)).lead == direct
    assert (await journal.claim("retrieve", "second", now=NOW)).lead == CONSEQUENCE
    assert (await journal.claim("retrieve", "third", now=NOW)).lead == weak
    retained = await journal.read(run.scan_id)
    assert retained.reports == () and retained.events == ()


async def test_full_version4_journal_remains_inspectable_during_ranking_upgrade(
    tmp_path,
):
    path = tmp_path / "full.sqlite"
    limit = 2 * 1024 * 1024
    journal = SQLiteCollectionJournal(path, maximum_bytes=limit)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(14, NOW))
    article = DiscoveryArticle(
        SourceReference(
            "controlled",
            "Local Daily",
            "Flood survivors describe recovery",
            "https://daily.example/retained",
            NOW,
            None,
            NOW,
        ),
        "Two people died in the flood. Survivors await new homes.",
        bylines=("A. Reporter",),
    )
    run = replace(run, reports=(assess_article(article, run.interval),))
    partition = CollectionPartition(
        "controlled", "flood", NOW - timedelta(days=14), NOW
    )
    leads = tuple(
        replace(
            CONSEQUENCE,
            external_id=str(index),
            canonical_url=f"https://daily.example/story-{index}",
            title=CONSEQUENCE.title if index % 2 else "Local community update",
        )
        for index in range(600)
    )
    await journal.attach(run, (partition,), now=NOW, budget=10)
    search = await journal.claim("search", "index", now=NOW)
    assert await journal.commit_page(search, CollectionPage(leads=leads), now=NOW)
    retained = await journal.read(run.scan_id)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE work SET priority=0 WHERE kind='retrieve'")
        db.execute("PRAGMA user_version=4")
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
    assert await restarted.read(run.scan_id) == retained
    assert (await restarted.read(run.scan_id)).reports[0].article == article
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 600
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert (
            db.execute(
                "SELECT COUNT(*) FROM work WHERE kind='retrieve' AND priority!=0"
            ).fetchone()[0]
            == 0
        )
    expanded = SQLiteCollectionJournal(path, maximum_bytes=2 * limit)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
    claim = await expanded.claim("retrieve", "publisher", now=NOW)
    assert claim is not None
    assert claim.lead.title == CONSEQUENCE.title
    assert await expanded.read(run.scan_id) == retained


async def test_noncapacity_migration_errors_are_not_silenced(tmp_path):
    path = tmp_path / "blocked.sqlite"
    journal = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(14, NOW))
    partition = CollectionPartition(
        "controlled", "flood", NOW - timedelta(days=14), NOW
    )
    await journal.attach(run, (partition,), now=NOW, budget=10)
    search = await journal.claim("search", "index", now=NOW)
    await journal.commit_page(search, CollectionPage(leads=(CONSEQUENCE,)), now=NOW)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE work SET priority=0 WHERE kind='retrieve'")
        db.execute("PRAGMA user_version=4")
        db.execute(
            "CREATE TRIGGER block_ranking BEFORE UPDATE OF priority ON work "
            "WHEN NEW.kind='retrieve' BEGIN "
            "SELECT RAISE(ABORT,'ranking update blocked'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="ranking update blocked"):
        SQLiteCollectionJournal(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
