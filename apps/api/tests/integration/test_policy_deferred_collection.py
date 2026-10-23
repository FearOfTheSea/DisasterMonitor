"""Publisher policy waits remain pending without spending the failure allowance."""

import sqlite3
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


async def test_policy_waits_survive_more_than_four_continuations_without_failing(
    tmp_path,
):
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, now))
    partition = CollectionPartition("controlled", "flood", now - timedelta(days=1), now)
    await journal.attach(run, (partition,), now=now, budget=10)
    search = await journal.claim("search", "search", now=now)
    item = NewsFeedItem(
        "one", "Publisher", "Flood", "https://publisher.example/one", None, None
    )
    await journal.commit_page(search, CollectionPage(leads=(item,)), now=now)
    for number in range(1, 7):
        work = await journal.claim("retrieve", "reader", now=now)
        assert work is not None and work.attempts == number
        retry = now + timedelta(seconds=10)
        await journal.fail(
            work,
            outcome="policy_deferred",
            detail="Publisher robots timing.",
            now=now,
            retry_at=retry,
        )
        progress = (await journal.snapshot(run.scan_id, now=now)).progress
        assert progress.articles_pending == 1
        assert progress.articles_unavailable == 0
        await journal.finish_pass(now=now)
        now = retry
        journal = SQLiteCollectionJournal(path)
        await journal.continue_scan(run.scan_id, now=now, budget=10)
    work = await journal.claim("retrieve", "reader", now=now)
    assert work is not None and work.attempts == 7
    await journal.commit_article(
        work,
        DiscoveryArticle(
            SourceReference(
                "news",
                "Publisher",
                "Flood",
                item.canonical_url,
                now,
                None,
                now,
            ),
            "Police said two people died in the flood.",
        ),
        now=now,
    )
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM attempts WHERE outcome='policy_deferred'"
            ).fetchone()[0]
            == 6
        )
        assert (
            db.execute(
                "SELECT count(*) FROM attempts WHERE outcome='article_retrieved'"
            ).fetchone()[0]
            == 1
        )
    assert (
        await journal.snapshot(run.scan_id, now=now)
    ).progress.articles_retrieved == 1


async def test_real_failure_allowance_still_exhausts_after_policy_deferrals(tmp_path):
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, now))
    partition = CollectionPartition("controlled", "flood", now - timedelta(days=1), now)
    await journal.attach(run, (partition,), now=now, budget=20)
    search = await journal.claim("search", "search", now=now)
    item = NewsFeedItem(
        "one", "Publisher", "Flood", "https://publisher.example/one", None, None
    )
    await journal.commit_page(search, CollectionPage(leads=(item,)), now=now)
    for outcome in ["policy_deferred"] * 5 + ["rate_limited"] * 4:
        work = await journal.claim("retrieve", "reader", now=now)
        assert work is not None
        retry = now + timedelta(seconds=10)
        await journal.fail(
            work,
            outcome=outcome,
            detail="Controlled timing/refusal.",
            now=now,
            retry_at=retry,
        )
        now = retry
    assert await journal.claim("retrieve", "exhausted", now=now) is None
    progress = (await journal.snapshot(run.scan_id, now=now)).progress
    assert progress.articles_pending == 0 and progress.articles_unavailable == 1
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT attempts,policy_deferrals FROM work WHERE kind='retrieve'"
        ).fetchone() == (9, 5)


async def test_delayed_redirect_survives_restarts_while_healthy_host_runs(
    tmp_path,
):
    import httpx

    from disaster_monitor.application.incidents.resumable_discovery import (
        ResumableDiscovery,
    )
    from disaster_monitor.infrastructure.news.collection_providers import (
        PublicCollectionArticleReader,
    )
    from disaster_monitor.infrastructure.news.public_documents import (
        PublicDocumentReader,
    )
    from disaster_monitor.infrastructure.operations import sqlite_public_document_access

    now = [datetime(2026, 10, 23, 12, tzinfo=UTC).timestamp()]
    calls = []
    items = tuple(
        NewsFeedItem(str(i), host, "Flood", f"https://{host}/{i}", None, None)
        for i, host in enumerate(("slow.example", "slow.example", "healthy.example"))
    )

    class Provider:
        source_id = "controlled"
        queries = ("flood",)
        supports_time_filter = False
        supports_alternates = False

        async def fetch_page(self, partition):
            return CollectionPage(leads=items)

    def respond(request):
        host = request.headers["host"]
        calls.append((host, request.url.path, now[0]))
        if request.url.path == "/robots.txt":
            policy = "User-agent: *\nDisallow:" + (
                "\nCrawl-delay: 600" if host == "slow.example" else ""
            )
            return httpx.Response(200, text=policy)
        if host == "slow.example" and request.url.path == "/0":
            return httpx.Response(301, headers={"Location": "/final"})
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text="""
        <meta property="article:published_time" content="2026-10-23T09:00:00Z">
        <article><p>Police reported two flood deaths.</p></article>""",
        )

    path = tmp_path / "journal.sqlite"
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        scan_id = None
        for index in range(4):
            reader = PublicDocumentReader(
                client=client,
                resolver=lambda host: ("93.184.216.34",),
                access=sqlite_public_document_access.SQLitePublicDocumentAccess(path),
                clock=lambda: now[0],
            )
            runtime = ResumableDiscovery(
                (Provider(),),
                PublicCollectionArticleReader(reader=reader),
                SQLiteCollectionJournal(path),
                clock=lambda: datetime.fromtimestamp(now[0], UTC),
                pass_seconds=0.5,
            )
            run = (
                await runtime.start(1)
                if scan_id is None
                else await runtime.continue_collection(scan_id)
            )
            scan_id = run.scan_id
            await runtime.wait(scan_id)
            result = await runtime.get(scan_id)
            if index == 0:
                assert len(result.reports) == 1
                assert (
                    result.reports[0].article.source.canonical_url
                    == items[2].canonical_url
                )
                assert result.collection.articles_unavailable == 0
            if result.collection.retry_at:
                now[0] = result.collection.retry_at.timestamp()
            await runtime.aclose()
        assert len(result.reports) == 3
        assert not result.collection.can_continue
    slow = [(path, at) for host, path, at in calls if host == "slow.example"]
    assert slow[0][0] == "/robots.txt"
    assert sorted(path for path, _ in slow) == ["/0", "/1", "/final", "/robots.txt"]
    assert all(
        later[1] - earlier[1] >= 600
        for earlier, later in zip(slow, slow[1:], strict=False)
    )


async def test_legacy_journal_upgrade_preserves_attempts_evidence_and_cooldowns(
    tmp_path,
):
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCollectionJournal(path)
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, now))
    part = CollectionPartition("controlled", "flood", now - timedelta(days=1), now)
    await journal.attach(run, (part,), now=now, budget=10)
    work = await journal.claim("search", "search", now=now)
    deadline = now + timedelta(hours=1)
    await journal.fail(
        work, outcome="rate_limited", detail="HTTP429", now=now, retry_at=deadline
    )
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE work DROP COLUMN policy_deferrals")
        saved_work = db.execute(
            "SELECT id,payload,state,attempts,due,outcome FROM work"
        ).fetchall()
        saved_attempts = db.execute("SELECT * FROM attempts").fetchall()
        saved_scans = db.execute("SELECT * FROM scans").fetchall()
        saved_cooldowns = db.execute("SELECT * FROM cooldowns").fetchall()
    upgraded = SQLiteCollectionJournal(path)
    assert await upgraded.claim("search", "before-deadline", now=now) is None
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT id,payload,state,attempts,due,outcome FROM work"
            ).fetchall()
            == saved_work
        )
        assert db.execute("SELECT * FROM attempts").fetchall() == saved_attempts
        assert db.execute("SELECT * FROM scans").fetchall() == saved_scans
        assert db.execute("SELECT * FROM cooldowns").fetchall() == saved_cooldowns
        assert db.execute("SELECT policy_deferrals FROM work").fetchall() == [(0,)]
