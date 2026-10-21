"""Controlled end-to-end collection, with real persistence and fake provider ports."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.incidents.resumable_discovery import (
    ResumableDiscovery,
)
from disaster_monitor.domain.collection import CollectionPage, CollectionProviderError
from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


def article(url="https://publisher.example/flood", at=NOW):
    return DiscoveryArticle(
        SourceReference(
            "controlled", "Publisher", "Flood in Riverton", url, at, None, NOW
        ),
        "Floods struck Riverton on October 18, 2026. Officials "
        "said two people died in the flood.",
    )


class Provider:
    source_id = "controlled"
    supports_alternates = False
    supports_time_filter = True
    queries = ("flood",)

    def __init__(self):
        self.calls = []

    async def fetch_page(self, partition):
        self.calls.append(partition)
        return CollectionPage(articles=(article(),))


class Reader:
    async def retrieve(self, lead):
        return article(lead.canonical_url)


async def test_unexpected_worker_failure_pauses_scan_and_keeps_same_work_resumable(
    tmp_path,
):
    class InterruptedJournal(SQLiteCollectionJournal):
        interrupted = False

        async def claim(self, kind, worker, *, now, provider=None):
            if kind == "search" and not self.interrupted:
                self.interrupted = True
                raise RuntimeError("Controlled journal interruption")
            return await super().claim(kind, worker, now=now, provider=provider)

    store = InterruptedJournal(tmp_path / "jobs.sqlite")
    provider = Provider()
    service = ResumableDiscovery((provider,), Reader(), store, clock=lambda: NOW)
    run = await service.start(1)
    try:
        with pytest.raises(RuntimeError, match="Controlled journal interruption"):
            await service.wait(run.scan_id)
        paused = await service.get(run.scan_id)
        assert paused.status == "incomplete"
        assert paused.collection.state == "partial"
        assert paused.collection.can_continue
        assert paused.collection.searches_pending == 1
        assert not await store.active_scans()
        assert not provider.calls

        continued = await service.continue_collection(run.scan_id)
        assert continued.interval == run.interval
        await service.wait(run.scan_id)
        finished = await service.get(run.scan_id)
        assert finished.status == "completed"
        assert len(finished.reports) == len(provider.calls) == 1
    finally:
        await service.aclose()


async def test_compatible_users_share_acquisition_but_keep_each_exact_interval(
    tmp_path,
):
    now = [NOW]
    provider = Provider()
    store = SQLiteCollectionJournal(tmp_path / "jobs.sqlite")
    service = ResumableDiscovery((provider,), Reader(), store, clock=lambda: now[0])
    first = await service.start(1)
    now[0] += timedelta(microseconds=1)
    second = await service.start(1)
    assert first.scan_id != second.scan_id
    assert first.interval.end != second.interval.end
    await service.wait(first.scan_id)
    assert len(provider.calls) == 1
    assert (await service.get(first.scan_id)).reports[0].eligibility == "eligible"
    assert (await service.get(second.scan_id)).interval == second.interval
    await service.aclose()


async def test_slow_article_does_not_block_subsequent_lead_pages(tmp_path):
    gate = asyncio.Event()
    second_page = asyncio.Event()

    class Paged(Provider):
        async def fetch_page(self, partition):
            if partition.cursor:
                second_page.set()
                return CollectionPage()
            return CollectionPage(
                leads=(
                    NewsFeedItem(
                        "one",
                        "Publisher",
                        "Flood in Riverton",
                        "https://publisher.example/blocked",
                        None,
                        None,
                        NOW,
                    ),
                ),
                next_cursor="next",
            )

    class SlowReader:
        async def retrieve(self, lead):
            await gate.wait()
            return article(lead.canonical_url)

    service = ResumableDiscovery(
        (Paged(),),
        SlowReader(),
        SQLiteCollectionJournal(tmp_path / "jobs.sqlite"),
        clock=lambda: NOW,
    )
    run = await service.start(1)
    await asyncio.wait_for(second_page.wait(), 2)
    gate.set()
    await service.wait(run.scan_id)
    assert (await service.get(run.scan_id)).collection.pages_acquired == 2
    await service.aclose()


async def test_budget_continue_and_restart_resume_same_cursor(tmp_path):
    class Paged(Provider):
        async def fetch_page(self, partition):
            self.calls.append(partition.cursor)
            return CollectionPage(
                articles=(article(),),
                next_cursor="next" if not partition.cursor else None,
            )

    path = tmp_path / "jobs.sqlite"
    provider = Paged()
    service = ResumableDiscovery(
        (provider,),
        Reader(),
        SQLiteCollectionJournal(path),
        clock=lambda: NOW,
        page_budget=1,
    )
    run = await service.start(1)
    await service.wait(run.scan_id)
    first = await service.get(run.scan_id)
    assert first.status == "incomplete"
    assert first.collection.can_continue
    await service.aclose()
    restarted = ResumableDiscovery(
        (provider,),
        Reader(),
        SQLiteCollectionJournal(path),
        clock=lambda: NOW,
        page_budget=1,
    )
    continued = await restarted.continue_collection(run.scan_id)
    assert continued.interval == run.interval
    await restarted.wait(run.scan_id)
    assert provider.calls == ["", "next"]
    assert (await restarted.get(run.scan_id)).status == "completed"
    await restarted.aclose()


async def test_unknown_publication_is_article_uncertainty_not_collection_failure(
    tmp_path,
):
    class Undated(Provider):
        async def fetch_page(self, partition):
            known = article()
            return CollectionPage(
                articles=(
                    replace(known, source=replace(known.source, published_at=None)),
                )
            )

    service = ResumableDiscovery(
        (Undated(),),
        Reader(),
        SQLiteCollectionJournal(tmp_path / "jobs.sqlite"),
        clock=lambda: NOW,
    )
    run = await service.start(1)
    await service.wait(run.scan_id)
    result = await service.get(run.scan_id)
    assert result.status == "completed"
    assert result.collection.state == "finished"
    assert result.reports[0].eligibility == "unknown_publication"
    assert not result.events
    await service.aclose()


async def test_provider_refusal_keeps_healthy_reports_visible(tmp_path):
    class Refused(Provider):
        source_id = "refused"

        async def fetch_page(self, partition):
            raise CollectionProviderError("access_refused", "HTTP 403")

    service = ResumableDiscovery(
        (Refused(), Provider()),
        Reader(),
        SQLiteCollectionJournal(tmp_path / "jobs.sqlite"),
        clock=lambda: NOW,
    )
    run = await service.start(1)
    await service.wait(run.scan_id)
    result = await service.get(run.scan_id)
    assert result.reports and result.events
    assert result.collection.searches_refused == 1
    assert result.status == "incomplete"
    await service.aclose()


async def test_startup_resumes_interrupted_article_without_repeating_saved_search(
    tmp_path,
):
    now = [NOW]
    reading = asyncio.Event()

    class Leads(Provider):
        async def fetch_page(self, partition):
            self.calls.append(partition)
            return CollectionPage(
                leads=(
                    NewsFeedItem(
                        "one",
                        "Publisher",
                        "Flood in Riverton",
                        "https://publisher.example/flood",
                        None,
                        None,
                        NOW,
                    ),
                )
            )

    class Interrupted:
        async def retrieve(self, lead):
            reading.set()
            await asyncio.Event().wait()

    path = tmp_path / "jobs.sqlite"
    provider = Leads()
    service = ResumableDiscovery(
        (provider,), Interrupted(), SQLiteCollectionJournal(path), clock=lambda: now[0]
    )
    run = await service.start(1)
    await asyncio.wait_for(reading.wait(), 2)
    await service.aclose()
    now[0] += timedelta(seconds=91)
    restarted = ResumableDiscovery(
        (provider,), Reader(), SQLiteCollectionJournal(path), clock=lambda: now[0]
    )
    await restarted.recover()
    await restarted.wait(run.scan_id)
    result = await restarted.get(run.scan_id)
    assert len(provider.calls) == 1
    assert result.collection.pages_acquired == 1
    assert result.collection.articles_retrieved == 1
    assert result.status == "completed"
    await restarted.aclose()


async def test_blocked_article_gets_one_alternate_search_with_actual_report_attribution(
    tmp_path,
):
    class Alternatives(Provider):
        supports_alternates = True

        async def fetch_page(self, partition):
            self.calls.append(partition)
            url = (
                "https://alternative.example/flood"
                if partition.alternate_for
                else "https://blocked.example/flood"
            )
            return CollectionPage(
                leads=(
                    NewsFeedItem(
                        url,
                        "Alternative" if partition.alternate_for else "Blocked",
                        "Flood in Riverton",
                        url,
                        None,
                        None,
                        NOW,
                    ),
                )
            )

    class Accessible:
        async def retrieve(self, lead):
            if "blocked.example" in lead.canonical_url:
                raise ValueError("Publisher access refused")
            report = article(lead.canonical_url)
            return replace(
                report, source=replace(report.source, publisher=lead.publisher)
            )

    provider = Alternatives()
    service = ResumableDiscovery(
        (provider,),
        Accessible(),
        SQLiteCollectionJournal(tmp_path / "jobs.sqlite"),
        clock=lambda: NOW,
    )
    run = await service.start(1)
    await service.wait(run.scan_id)
    result = await service.get(run.scan_id)
    assert len(provider.calls) == 2
    assert provider.calls[1].alternate_for == "https://blocked.example/flood"
    assert result.reports[0].article.source.publisher == "Alternative"
    assert result.collection.articles_unavailable == 1
    assert result.collection.leads_acquired == 2
    assert result.status == "completed"
    await service.aclose()
