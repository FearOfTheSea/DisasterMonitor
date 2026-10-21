"""Durable collection, independent article workers and progressive projection."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from random import random
from time import monotonic
from typing import Literal
from uuid import uuid4

from disaster_monitor.application.incidents.collection_planning import (
    plan_alternate_reports,
    plan_collection,
)
from disaster_monitor.application.ports.collection import (
    COLLECTION_RATE_LIMIT_MINIMUM_SECONDS,
    CollectionArticleReader,
    CollectionJournal,
    CollectionProvider,
)
from disaster_monitor.application.ports.discovery import DiscoveryCapacityError
from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    CollectionProviderError,
)
from disaster_monitor.domain.discovery import (
    CollectionProgress,
    DiscoveryRun,
    ReportingInterval,
    assess_article,
    group_reports,
    supplement_events,
)

logger = logging.getLogger(__name__)


class ResumableDiscovery:
    def __init__(
        self,
        providers: tuple[CollectionProvider, ...],
        reader: CollectionArticleReader,
        journal: CollectionJournal,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        page_budget: int = 28,
        pass_seconds: float = 180,
        article_timeout: float = 20,
        country_names: frozenset[str] = frozenset(),
    ) -> None:
        self._providers = providers
        self._by_provider = {p.source_id: p for p in providers}
        self._reader = reader
        self._journal = journal
        self._clock = clock
        self._budget = page_budget
        self._pass_seconds = pass_seconds
        self._article_timeout = article_timeout
        self._country_names = country_names
        self._pump_task: asyncio.Task[None] | None = None
        self._restart_requested = False
        self._projection_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._dirty = asyncio.Event()
        self._capacity_reached = asyncio.Event()

    async def start(self, days: int = 7) -> DiscoveryRun:
        now = self._clock()
        run = DiscoveryRun(
            str(uuid4()),
            ReportingInterval.at_start(days, now),
            collection=CollectionProgress(),
        )
        partitions = plan_collection(run.interval, self._providers, observed_at=now)
        async with self._lifecycle_lock:
            await self._journal.attach(run, partitions, now=now, budget=self._budget)
            self._kick()
        return run

    async def get(self, scan_id: str) -> DiscoveryRun:
        run = await self._journal.read(scan_id)
        if run is None:
            raise LookupError("Scan not found or retained scan expired.")
        return run

    async def continue_collection(self, scan_id: str) -> DiscoveryRun:
        async with self._lifecycle_lock:
            await self._journal.continue_scan(
                scan_id, now=self._clock(), budget=self._budget
            )
            self._kick()
        return await self.get(scan_id)

    def _kick(self) -> None:
        self._dirty.set()
        if self._pump_task is None or self._pump_task.done():
            self._restart_requested = False
            self._pump_task = asyncio.create_task(self._pump())
            self._pump_task.add_done_callback(self._pump_finished)
        else:
            self._restart_requested = True

    def _pump_finished(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        task.exception()
        if self._pump_task is task and self._restart_requested:
            self._kick()

    async def recover(self) -> None:
        # Persisted cursors, attempts, budgets, leases and cooldowns remain unchanged.
        if await self._journal.active_scans():
            self._kick()

    async def wait(self, scan_id: str) -> None:
        while task := self._pump_task:
            await asyncio.shield(task)
            if self._pump_task is task:
                return

    async def _pump(self) -> None:
        began = monotonic()
        finishing_ids: tuple[str, ...] = ()
        self._capacity_reached.clear()
        projector = asyncio.create_task(self._project_periodically())
        try:
            while monotonic() - began < self._pass_seconds:
                searches_done = asyncio.Event()
                retrievals = [
                    asyncio.create_task(self._article_worker(searches_done, str(i)))
                    for i in range(2)
                ]
                searches = [
                    asyncio.create_task(self._search_worker(p.source_id))
                    for p in self._providers
                ]
                try:
                    await asyncio.gather(*searches)
                    searches_done.set()
                    await asyncio.gather(*retrievals)
                finally:
                    searches_done.set()
                    for task in (*searches, *retrievals):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*searches, *retrievals, return_exceptions=True)
                if self._capacity_reached.is_set():
                    raise DiscoveryCapacityError()
                retry = await self._journal.next_retry(now=self._clock())
                if retry is None:
                    break
                wait = max(0, (retry - self._clock()).total_seconds())
                if monotonic() - began + wait >= self._pass_seconds:
                    break
                await asyncio.sleep(min(max(wait, 0.05), 1))
            async with self._lifecycle_lock:
                ids = await self._journal.active_scans()
                finishing_ids = ids
                await self._journal.finish_pass(now=self._clock())
                for scan_id in ids:
                    await self._project(scan_id)
                # Requests accepted before this lock have been handled. A later
                # request must start another pump after this one's cleanup.
                self._restart_requested = False
        except DiscoveryCapacityError:
            projector.cancel()
            await asyncio.gather(projector, return_exceptions=True)
            async with self._lifecycle_lock:
                self._restart_requested = False
                await self._journal.suspend_at_capacity(
                    now=self._clock(), scan_ids=finishing_ids
                )
        except asyncio.CancelledError:
            # No terminal rewrite: startup reclaims expired leases and continues
            # the same pass. Budget consumption already survived the interruption.
            raise
        except Exception:
            logger.exception("Durable discovery worker failed; journal retained")
            projector.cancel()
            await asyncio.gather(projector, return_exceptions=True)
            # A stopped worker must not leave a live pass and disable Continue.
            # Finish only the pass: work, leases, attempts and cooldowns survive.
            try:
                async with self._lifecycle_lock:
                    self._restart_requested = False
                    ids = await self._journal.active_scans()
                    await self._journal.finish_pass(now=self._clock())
                    for scan_id in ids:
                        await self._project(scan_id)
            except Exception:
                logger.exception("Failed to persist paused discovery state")
            raise
        finally:
            projector.cancel()
            await asyncio.gather(projector, return_exceptions=True)

    async def _search_worker(self, worker: str) -> None:
        while not self._capacity_reached.is_set():
            work = await self._journal.claim(
                "search", "search:" + worker, now=self._clock(), provider=worker
            )
            if work is None:
                return
            try:
                if work.partition is None or work.provider not in self._by_provider:
                    raise CollectionProviderError(
                        "access_refused",
                        "Configured discovery provider is unavailable.",
                    )
                page = await self._by_provider[work.provider].fetch_page(work.partition)
                await self._journal.commit_page(work, page, now=self._clock())
            except DiscoveryCapacityError:
                raise
            except CollectionProviderError as error:
                await self._record_error(work, error)
            except Exception:
                await self._record_error(
                    work,
                    CollectionProviderError(
                        "transport_failed", "News service attempt failed."
                    ),
                )
            self._dirty.set()

    async def _record_error(
        self, work: ClaimedCollectionWork, error: CollectionProviderError
    ) -> None:
        now = self._clock()
        retry_at = None
        if error.outcome in ("rate_limited", "transport_failed"):
            minimum = (
                COLLECTION_RATE_LIMIT_MINIMUM_SECONDS
                if error.outcome == "rate_limited"
                else min(300, 30 * 2 ** (work.attempts - 1))
            )
            delay = max(error.retry_after_seconds or 0, minimum + random() * 5)
            retry_at = now + timedelta(seconds=delay)
        await self._journal.fail(
            work,
            outcome=error.outcome,
            detail=f"{work.provider}: {error.detail}",
            now=now,
            retry_at=retry_at,
            alternates=plan_alternate_reports(work, self._providers, observed_at=now)
            if work.kind == "retrieve" and work.attempts == 1
            else (),
        )

    async def _article_worker(self, searches_done: asyncio.Event, worker: str) -> None:
        while not self._capacity_reached.is_set():
            work = await self._journal.claim(
                "retrieve", "article:" + worker, now=self._clock()
            )
            if work is None:
                if searches_done.is_set():
                    return
                await asyncio.sleep(0.05)
                continue
            try:
                assert work.lead is not None
                async with asyncio.timeout(self._article_timeout):
                    article = await self._reader.retrieve(work.lead)
                await self._journal.commit_article(work, article, now=self._clock())
            except DiscoveryCapacityError:
                raise
            except Exception as error:
                if (
                    isinstance(error, CollectionProviderError)
                    and error.outcome == "rate_limited"
                ):
                    await self._record_error(work, error)
                    self._dirty.set()
                    continue
                # A bounded outcome retains the lead and actual provider attribution.
                # Do not retain exception messages that may contain sensitive URLs.
                await self._journal.fail(
                    work,
                    outcome="article_unavailable",
                    detail=error.detail
                    if isinstance(error, CollectionProviderError)
                    else f"Publisher article unavailable ({type(error).__name__}).",
                    now=self._clock(),
                    alternates=plan_alternate_reports(
                        work, self._providers, observed_at=self._clock()
                    ),
                )
            self._dirty.set()

    async def _project_periodically(self) -> None:
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            try:
                for scan_id in await self._journal.active_scans():
                    await self._project(scan_id)
            except DiscoveryCapacityError:
                self._capacity_reached.set()
                return
            await asyncio.sleep(1)

    async def _project(self, scan_id: str) -> None:
        async with self._projection_lock:
            snapshot = await self._journal.snapshot(scan_id, now=self._clock())
            run = snapshot.run
            progress = snapshot.progress
            reports_by_url = {}
            retained = {r.article.source.canonical_url: r for r in run.reports}
            for article in sorted(
                snapshot.articles, key=lambda a: a.source.retrieved_at
            ):
                url = article.source.canonical_url
                old = retained.get(url)
                reports_by_url[url] = (
                    old
                    if old and old.article == article
                    else await asyncio.to_thread(
                        assess_article,
                        article,
                        run.interval,
                        country_names=self._country_names,
                    )
                )
            reports = tuple(reports_by_url.values())
            grouped = await asyncio.to_thread(group_reports, reports, run.events)
            events = await asyncio.to_thread(
                supplement_events, grouped, snapshot.supplemental
            )
            status: Literal["running", "completed", "incomplete"] = (
                "running"
                if progress.state in ("collecting", "waiting")
                else "completed"
                if progress.state == "finished"
                else "incomplete"
            )
            notices = progress.notices
            if progress.searches_pending or progress.articles_pending:
                notices = (
                    *notices,
                    "Collection has remaining work. Continue collection "
                    "keeps this reporting interval.",
                )
            result = replace(
                run,
                reports=reports,
                events=events,
                collection=progress,
                supplemental=snapshot.supplemental,
                status=status,
                finished_at=None if status == "running" else self._clock(),
                issues=notices,
                successful_operations=progress.pages_acquired,
                failed_operations=progress.searches_refused
                + progress.articles_unavailable,
                truncated=bool(
                    progress.searches_pending or progress.searches_saturated
                ),
            )
            # Once persistence has begun, cancellation cannot roll back a journal
            # adapter's background transaction. Drain it before releasing the
            # projection lock or recording a capacity stop.
            saving = asyncio.create_task(self._journal.save(result))
            try:
                await asyncio.shield(saving)
            except asyncio.CancelledError:
                await saving
                raise

    async def aclose(self) -> None:
        self._restart_requested = False
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()
            await asyncio.gather(self._pump_task, return_exceptions=True)
