"""Publisher refusal scheduling survives restarts without stopping other hosts."""

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_providers import (
    PublicCollectionArticleReader,
)
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)


def lead(host, path):
    return NewsFeedItem(path, host, "Floods", f"https://{host}/{path}", None, None, NOW)


def article(item):
    return DiscoveryArticle(
        SourceReference("news", "Daily", "Floods", item.canonical_url, NOW, None, NOW),
        "Floods struck Riverton. Two people died.",
    )


async def prepare(store):
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))
    partition = CollectionPartition("news", "flood", NOW - timedelta(days=1), NOW)
    await store.attach(run, (partition,), now=NOW, budget=10)
    work = await store.claim("search", "search", now=NOW)
    await store.commit_page(
        work,
        CollectionPage(
            leads=(
                lead("blocked.example", "one"),
                lead("blocked.example", "two"),
                lead("healthy.example", "three"),
            )
        ),
        now=NOW,
    )
    return run


async def test_article_adapter_retains_retry_after_without_repeating_request():
    calls = []

    class Refused:
        async def read(self, url):
            calls.append(url)
            request = httpx.Request("GET", url)
            response = httpx.Response(
                429, request=request, headers={"Retry-After": "1800"}
            )
            response.raise_for_status()

    with pytest.raises(CollectionProviderError) as failure:
        await PublicCollectionArticleReader(reader=Refused()).retrieve(
            lead("blocked.example", "one")
        )
    assert failure.value.outcome == "rate_limited"
    assert failure.value.retry_after_seconds == 1800
    assert len(calls) == 1


async def test_publisher_cooldown_survives_restart_and_continue_but_healthy_host_runs(
    tmp_path,
):
    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    run = await prepare(store)
    blocked = await store.claim("retrieve", "first", now=NOW)
    retry = NOW + timedelta(hours=1)
    await store.fail(
        blocked,
        outcome="rate_limited",
        detail="Publisher HTTP 429.",
        now=NOW,
        retry_at=retry,
    )
    healthy = await store.claim("retrieve", "second", now=NOW)
    assert healthy.lead.canonical_url == "https://healthy.example/three"
    await store.commit_article(healthy, article(healthy.lead), now=NOW)
    assert await store.claim("retrieve", "third", now=NOW) is None
    progress = (await store.snapshot(run.scan_id, now=NOW)).progress
    assert progress.articles_pending == 2
    assert progress.retry_at == retry
    await store.finish_pass(now=NOW)
    restarted = SQLiteCollectionJournal(path)
    await restarted.continue_scan(run.scan_id, now=NOW, budget=10)
    assert await restarted.claim("retrieve", "after-restart", now=NOW) is None
    await restarted.finish_pass(now=retry)
    await restarted.continue_scan(run.scan_id, now=retry, budget=10)
    assert (
        await restarted.claim("retrieve", "after-deadline", now=retry)
    ).lead.canonical_url.startswith("https://blocked.example/")


async def test_publisher_leases_survive_restart_and_serialize_one_host_only(tmp_path):
    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    await prepare(store)
    first = await store.claim("retrieve", "first", now=NOW)
    second = await store.claim("retrieve", "second", now=NOW)
    assert first.lead.canonical_url == "https://blocked.example/one"
    assert second.lead.canonical_url == "https://healthy.example/three"
    restarted = SQLiteCollectionJournal(path)
    assert (
        await restarted.claim("retrieve", "too-soon", now=NOW + timedelta(seconds=1))
        is None
    )
    await restarted.commit_article(first, article(first.lead), now=NOW)
    third = await restarted.claim("retrieve", "released", now=NOW)
    assert third.lead.canonical_url == "https://blocked.example/two"


async def test_active_publisher_lease_is_running_work_not_a_service_retry(tmp_path):
    store = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    run = await prepare(store)
    await store.claim("retrieve", "first", now=NOW)
    await store.claim("retrieve", "second", now=NOW)
    progress = (await store.snapshot(run.scan_id, now=NOW)).progress
    assert progress.state == "collecting"
    assert progress.retry_at is None


async def test_expired_refusal_deadline_is_not_an_active_wait_after_restart(tmp_path):
    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    run = await prepare(store)
    blocked = await store.claim("retrieve", "first", now=NOW)
    deadline = NOW + timedelta(hours=1)
    await store.fail(
        blocked, outcome="rate_limited", detail="HTTP429", now=NOW, retry_at=deadline
    )
    await store.finish_pass(now=NOW)
    restarted = SQLiteCollectionJournal(path)
    await restarted.continue_scan(run.scan_id, now=deadline, budget=10)
    progress = (await restarted.snapshot(run.scan_id, now=deadline)).progress
    assert progress.state == "collecting"
    assert progress.retry_at is None
    assert await restarted.claim("retrieve", "after-wait", now=deadline) is not None


async def test_future_refusal_does_not_label_healthy_runnable_work_as_waiting(tmp_path):
    store = SQLiteCollectionJournal(tmp_path / "journal.sqlite")
    run = await prepare(store)
    blocked = await store.claim("retrieve", "first", now=NOW)
    deadline = NOW + timedelta(hours=1)
    await store.fail(
        blocked, outcome="rate_limited", detail="HTTP429", now=NOW, retry_at=deadline
    )
    progress = (await store.snapshot(run.scan_id, now=NOW)).progress
    assert progress.state == "collecting"
    assert progress.retry_at == deadline
    healthy = await store.claim("retrieve", "healthy", now=NOW)
    during = (await store.snapshot(run.scan_id, now=NOW)).progress
    assert during.state == "collecting"
    assert during.retry_at == deadline
    await store.commit_article(healthy, article(healthy.lead), now=NOW)
    waiting = (await store.snapshot(run.scan_id, now=NOW)).progress
    assert waiting.state == "waiting"
    assert waiting.retry_at == deadline


async def test_retained_legacy_refusal_defers_host_without_changing_evidence(tmp_path):
    path = tmp_path / "legacy.sqlite"
    store = SQLiteCollectionJournal(path)
    run = await prepare(store)
    original = await store.claim("retrieve", "legacy", now=NOW)
    await store.fail(
        original,
        outcome="article_unavailable",
        detail="Publisher HTTP 429; article access unavailable.",
        now=NOW,
    )
    await store.finish_pass(now=NOW)
    restarted = SQLiteCollectionJournal(path)
    await restarted.continue_scan(run.scan_id, now=NOW, budget=10)
    healthy = await restarted.claim("retrieve", "after-upgrade", now=NOW)
    assert healthy.lead.canonical_url == "https://healthy.example/three"
    await restarted.commit_article(healthy, article(healthy.lead), now=NOW)
    progress = (await restarted.snapshot(run.scan_id, now=NOW)).progress
    assert progress.articles_unavailable == 1
    assert progress.articles_pending == 1
    assert progress.retry_at >= NOW + timedelta(seconds=900)
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT outcome FROM work WHERE id=?", (original.work_id,)
            ).fetchone()[0]
            == "article_unavailable"
        )


@pytest.mark.parametrize("retry_after", [None, 1800])
async def test_article_worker_preserves_deadline_and_bounds_retries(
    tmp_path,
    retry_after,
):
    now = [NOW]
    calls = []

    class Provider:
        source_id = "controlled"
        queries = ("flood",)
        supports_time_filter = False
        supports_alternates = False

        async def fetch_page(self, partition):
            return CollectionPage(leads=(lead("blocked.example", "one"),))

    class Reader:
        async def retrieve(self, item):
            calls.append(item.canonical_url)
            raise CollectionProviderError(
                "rate_limited", "Publisher HTTP 429.", retry_after
            )

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path)
    service = ResumableDiscovery((Provider(),), Reader(), store, clock=lambda: now[0])
    run = await service.start(1)
    await service.wait(run.scan_id)
    assert len(calls) == 1
    progress = (await service.get(run.scan_id)).collection
    assert progress.articles_pending == 1
    if retry_after is None:
        assert (
            NOW + timedelta(seconds=900)
            <= progress.retry_at
            <= NOW + timedelta(seconds=905)
        )
    else:
        assert progress.retry_at == NOW + timedelta(seconds=1800)
    await service.aclose()
    service = ResumableDiscovery(
        (Provider(),), Reader(), SQLiteCollectionJournal(path), clock=lambda: now[0]
    )
    await service.continue_collection(run.scan_id)
    await service.wait(run.scan_id)
    assert len(calls) == 1
    for attempt in range(2, 5):
        now[0] += timedelta(seconds=2000)
        await service.continue_collection(run.scan_id)
        await service.wait(run.scan_id)
        assert len(calls) == attempt
    progress = (await service.get(run.scan_id)).collection
    assert progress.articles_unavailable == 1
    assert progress.articles_pending == 0
    assert not progress.can_continue
    await service.aclose()


async def test_rate_limited_host_allows_one_healthy_alternate(
    tmp_path,
):
    searches, reads = [], []

    class Provider:
        source_id = "controlled"
        queries = ("flood",)
        supports_time_filter = False
        supports_alternates = True

        async def fetch_page(self, partition):
            searches.append(partition)
            host = "healthy.example" if partition.alternate_for else "blocked.example"
            return CollectionPage(leads=(lead(host, "one"),))

    class Reader:
        async def retrieve(self, item):
            reads.append(item.canonical_url)
            if "blocked.example" in item.canonical_url:
                raise CollectionProviderError(
                    "rate_limited", "Publisher HTTP 429.", 1800
                )
            return article(item)

    service = ResumableDiscovery(
        (Provider(),),
        Reader(),
        SQLiteCollectionJournal(tmp_path / "journal.sqlite"),
        clock=lambda: NOW,
    )
    run = await service.start(1)
    await service.wait(run.scan_id)
    result = await service.get(run.scan_id)
    assert len(searches) == 2
    assert searches[1].alternate_for == "https://blocked.example/one"
    assert set(reads) == {"https://blocked.example/one", "https://healthy.example/one"}
    assert len(result.reports) == 1
    assert result.collection.articles_pending == 1
    await service.continue_collection(run.scan_id)
    await service.wait(run.scan_id)
    assert len(searches) == len(reads) == 2
    await service.aclose()


async def test_first_real_refusal_after_policy_wait_still_seeks_an_alternate(tmp_path):
    now, searches, reads = [NOW], [], []

    class Provider:
        source_id = "controlled"
        queries = ("flood",)
        supports_time_filter = False
        supports_alternates = True

        async def fetch_page(self, partition):
            searches.append(partition)
            host = "healthy.example" if partition.alternate_for else "blocked.example"
            return CollectionPage(leads=(lead(host, "one"),))

    class Reader:
        async def retrieve(self, item):
            reads.append(item.canonical_url)
            if "blocked.example" in item.canonical_url:
                if len(reads) == 1:
                    raise CollectionProviderError(
                        "policy_deferred", "Robots timing.", 10
                    )
                raise CollectionProviderError(
                    "rate_limited", "Publisher HTTP429.", 1800
                )
            return article(item)

    runtime = ResumableDiscovery(
        (Provider(),),
        Reader(),
        SQLiteCollectionJournal(tmp_path / "journal.sqlite"),
        clock=lambda: now[0],
        pass_seconds=0.5,
    )
    try:
        run = await runtime.start(1)
        await runtime.wait(run.scan_id)
        assert len(searches) == 1
        now[0] += timedelta(seconds=10)
        await runtime.continue_collection(run.scan_id)
        await runtime.wait(run.scan_id)
        result = await runtime.get(run.scan_id)
        assert len(searches) == 2
        assert searches[1].alternate_for == "https://blocked.example/one"
        assert len(result.reports) == 1
        assert result.collection.articles_pending == 1
    finally:
        await runtime.aclose()
