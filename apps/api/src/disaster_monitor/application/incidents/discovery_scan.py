"""Bounded, shared worldwide publication scans with incremental persistence."""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from disaster_monitor.application.incidents.discovery_reprocessing import (
    reprocess_retained_run,
)
from disaster_monitor.application.incidents.mention_geography import (
    resolve_event_places,
)
from disaster_monitor.application.ports.collection import CollectionRuntime
from disaster_monitor.application.ports.discovery import DiscoveryFeed, DiscoveryStore
from disaster_monitor.application.ports.mention_geography import MentionPlaceResolver
from disaster_monitor.domain.discovery import (
    DiscoveryRun,
    ReportingInterval,
    assess_article,
    group_reports,
    supplement_events,
)

logger = logging.getLogger(__name__)
_MAX_PENDING_REASSESSMENTS = 10


class DiscoveryScanService:
    def __init__(
        self,
        feeds: tuple[DiscoveryFeed, ...],
        store: DiscoveryStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        provider_timeout_seconds: float = 600,
        maximum_reports: int = 400,
        place_resolver: MentionPlaceResolver | None = None,
        country_names: frozenset[str] = frozenset(),
        collection: CollectionRuntime | None = None,
    ) -> None:
        self._feeds = feeds
        self._collection = collection
        self._store = store
        self._clock = clock
        self._timeout = provider_timeout_seconds
        self._maximum_reports = maximum_reports
        self._place_resolver = place_resolver
        self._country_names = country_names
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active: dict[int, DiscoveryRun] = {}
        self._lock = asyncio.Lock()
        self._persistence_failures: OrderedDict[str, DiscoveryRun] = OrderedDict()
        self._reprocessing: dict[str, str] = {}
        self._reprocessing_worker = asyncio.Semaphore(1)

    async def start(self, days: int = 7) -> DiscoveryRun:
        if self._collection:
            return await self._collection.start(days)
        interval = ReportingInterval.at_start(days, self._clock())
        async with self._lock:
            # Reuse only running work with the same period, started within 60s.
            active = self._active.get(days)
            if active and (interval.end - active.interval.end).total_seconds() <= 60:
                return await self.get(active.scan_id)
            if len(self._tasks) >= 5:
                raise ValueError(
                    "Five scans are already running. Please wait for one to finish."
                )
            run = DiscoveryRun(scan_id=str(uuid4()), interval=interval)
            await self._store.save(run)
            self._active[days] = run
            task = asyncio.create_task(self._execute(run))
            self._tasks[run.scan_id] = task
            task.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
            return run

    async def get(self, scan_id: str) -> DiscoveryRun:
        run = await self._retained_run(scan_id)
        if run.status == "running" and run.reprocessed_from:
            # Opening a persisted pending assessment after restart resumes that ID.
            async with self._lock:
                if (
                    scan_id not in self._tasks
                    and len(self._tasks) < _MAX_PENDING_REASSESSMENTS
                ):
                    original = await self._retained_run(run.reprocessed_from)
                    self._launch_reprocessing(run, original)
        return run

    async def _retained_run(self, scan_id: str) -> DiscoveryRun:
        if scan_id in self._persistence_failures:
            return self._persistence_failures[scan_id]
        if self._collection:
            return await self._collection.get(scan_id)
        run = await self._store.read(scan_id)
        if run is None:
            raise LookupError("Scan not found or retained scan expired.")
        return run

    async def reprocess(self, scan_id: str) -> DiscoveryRun:
        async with self._lock:
            original = await self._retained_run(scan_id)
            if original.reprocessed_from:
                original = await self._retained_run(original.reprocessed_from)
            if original.status == "running":
                raise ValueError(
                    "Wait until news acquisition has finished before reprocessing."
                )
            if pending_id := self._reprocessing.get(original.scan_id):
                return await self._retained_run(pending_id)
            if len(self._tasks) >= _MAX_PENDING_REASSESSMENTS:
                raise ValueError(
                    "Reassessment capacity reached. Wait for a running assessment "
                    "to finish."
                )
            pending = replace(
                original,
                scan_id=str(uuid4()),
                status="running",
                finished_at=None,
                reprocessed_from=original.scan_id,
                issues=(
                    *original.issues,
                    "Retained report reassessment is pending. Visible records are "
                    "the previous assessment; no new news acquisition is running.",
                ),
            )
            # Persist the recoverable job before acknowledging it to the browser.
            await self._persist_reassessment(pending)
            self._launch_reprocessing(pending, original)
            return pending

    def _launch_reprocessing(
        self, pending: DiscoveryRun, original: DiscoveryRun
    ) -> None:
        self._reprocessing[original.scan_id] = pending.scan_id
        task = asyncio.create_task(self._execute_reprocessing(pending, original))
        self._tasks[pending.scan_id] = task
        task.add_done_callback(
            lambda done: None if done.cancelled() else done.exception()
        )

    async def _persist_reassessment(self, run: DiscoveryRun) -> None:
        saving = asyncio.create_task(self._store.save(run))
        try:
            await asyncio.shield(saving)
        except asyncio.CancelledError:
            # File/SQLite writes already dispatched to a thread must finish before
            # shutdown or another writer can replace this assessment.
            await saving
            raise

    async def _execute_reprocessing(
        self, pending: DiscoveryRun, original: DiscoveryRun
    ) -> None:
        try:
            async with self._reprocessing_worker:
                result = await asyncio.to_thread(
                    reprocess_retained_run,
                    original,
                    scan_id=pending.scan_id,
                    at=self._clock(),
                    country_names=self._country_names,
                )
                await self._persist_reassessment(result)
        except asyncio.CancelledError:
            # The saved running assessment is recoverable through its existing URL.
            raise
        except Exception:
            logger.exception("Retained report reassessment failed: %s", pending.scan_id)
            failed = replace(
                pending,
                status="incomplete",
                finished_at=self._clock(),
                issues=(
                    *original.issues,
                    "Retained report reassessment failed. Previous assessment "
                    "records remain available; the original scan is unchanged.",
                ),
            )
            try:
                await self._persist_reassessment(failed)
            except Exception:
                logger.exception("Reassessment failure could not be persisted")
                self._persistence_failures[pending.scan_id] = replace(
                    failed,
                    issues=(
                        *failed.issues,
                        "Failure status is retained in this process only.",
                    ),
                )
                while len(self._persistence_failures) > 8:
                    self._persistence_failures.popitem(last=False)
        finally:
            self._tasks.pop(pending.scan_id, None)
            if self._reprocessing.get(original.scan_id) == pending.scan_id:
                self._reprocessing.pop(original.scan_id, None)

    async def wait(self, scan_id: str) -> None:
        if task := self._tasks.get(scan_id):
            await asyncio.shield(task)
            return
        if self._collection:
            await self._collection.wait(scan_id)
            return

    async def _execute(self, run: DiscoveryRun) -> None:
        try:
            for feed in self._feeds:
                try:
                    async with asyncio.timeout(self._timeout):
                        async for batch in feed.discover(interval=run.interval):
                            reports = {
                                r.article.source.canonical_url: r for r in run.reports
                            }
                            for article in batch.articles:
                                reports[article.source.canonical_url] = assess_article(
                                    article,
                                    run.interval,
                                    country_names=self._country_names,
                                )
                            capped = len(reports) > self._maximum_reports
                            retained = tuple(reports.values())[: self._maximum_reports]
                            supplemental = (*run.supplemental, *batch.supplemental)
                            grouped = await asyncio.to_thread(
                                group_reports, retained, run.events
                            )
                            projected = await asyncio.to_thread(
                                supplement_events, grouped, supplemental
                            )
                            run = replace(
                                run,
                                reports=retained,
                                events=projected,
                                supplemental=supplemental,
                                acquisition=(*run.acquisition, *batch.acquisition),
                                issues=tuple(
                                    dict.fromkeys(
                                        (
                                            *run.issues,
                                            *batch.issues,
                                            *(
                                                ("Article collection limit reached.",)
                                                if capped
                                                else ()
                                            ),
                                        )
                                    )
                                ),
                                successful_operations=run.successful_operations
                                + batch.successful_operations,
                                failed_operations=run.failed_operations
                                + batch.failed_operations,
                                truncated=run.truncated or batch.truncated or capped,
                            )
                            run = replace(
                                run,
                                events=tuple(
                                    replace(event, collection_notices=run.issues)
                                    for event in run.events
                                ),
                            )
                            await self._store.save(run)
                            if capped:
                                break
                except Exception:
                    run = replace(
                        run,
                        failed_operations=run.failed_operations + 1,
                        issues=(
                            *run.issues,
                            f"{feed.source_id}: acquisition failed or timed out; "
                            "available results retained.",
                        ),
                    )
            if self._place_resolver:
                run = replace(
                    run,
                    events=await resolve_event_places(run.events, self._place_resolver),
                )
            status: Literal["completed", "incomplete", "failed"] = "completed"
            if not run.successful_operations:
                status = "failed"
            elif run.failed_operations or run.truncated or run.issues:
                status = "incomplete"
            unknown = sum(r.eligibility == "unknown_publication" for r in run.reports)
            if unknown:
                run = replace(
                    run,
                    issues=(
                        *run.issues,
                        f"{unknown} reports have unknown publication times "
                        "and are excluded from window results.",
                    ),
                )
                if status == "completed":
                    status = "incomplete"
            run = replace(run, status=status, finished_at=self._clock())
            run = replace(
                run,
                events=tuple(
                    replace(
                        event,
                        collection_notices=tuple(
                            dict.fromkeys((*event.collection_notices, *run.issues))
                        ),
                    )
                    for event in run.events
                ),
            )
            await self._store.save(run)
        except asyncio.CancelledError:
            await self._store.save(
                replace(
                    run,
                    status="incomplete",
                    finished_at=self._clock(),
                    issues=(
                        *run.issues,
                        "Scan interrupted; retained results available.",
                    ),
                )
            )
            raise
        except Exception:
            logger.exception("Discovery scan persistence failed: %s", run.scan_id)
            notice = (
                "Scan persistence failed. Available results remain in this API "
                "process only; durable retention is unavailable."
            )
            self._persistence_failures[run.scan_id] = replace(
                run,
                status="incomplete" if run.reports else "failed",
                finished_at=self._clock(),
                issues=(*run.issues, notice),
                events=tuple(
                    replace(
                        event, collection_notices=(*event.collection_notices, notice)
                    )
                    for event in run.events
                ),
            )
            while len(self._persistence_failures) > 8:
                self._persistence_failures.popitem(last=False)
        finally:
            self._tasks.pop(run.scan_id, None)
            if self._active.get(run.interval.days, run).scan_id == run.scan_id:
                self._active.pop(run.interval.days, None)

    async def aclose(self) -> None:
        if self._collection:
            await self._collection.aclose()
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def continue_collection(self, scan_id: str) -> DiscoveryRun:
        if self._collection is None:
            raise ValueError(
                "This historical scan has no resumable collection "
                "journal. Start a new scan."
            )
        return await self._collection.continue_collection(scan_id)

    async def recover(self) -> None:
        if self._collection:
            await self._collection.recover()
