"""Autonomous, fail-closed generation and promotion of global country metadata."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx

from disaster_monitor.application.ports.geography import (
    CountryCatalogUpdateState,
    CountryCatalogUpdateStatus,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.infrastructure.geography.country_catalog_generation import (
    _source_versions,
    build_country_catalog_payload,
    serialize_country_catalog,
)
from disaster_monitor.infrastructure.geography.country_catalog_source import (
    CountryCatalogSource,
)
from disaster_monitor.infrastructure.geography.country_catalog_storage import (
    VersionedCountryCatalogStore,
    _deserialize_status,
    _json_object,
    _replace_status,
    _required_string,
    _serialize_status,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

_LOGGER = logging.getLogger(__name__)


class AutonomousCountryCatalogUpdater:
    """Generate and promote catalogs while retaining the last known-good version."""

    def __init__(
        self,
        *,
        catalog: StaticCountryCatalog,
        store: VersionedCountryCatalogStore,
        source: CountryCatalogSource,
        automatic_updates_enabled: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        minimum_country_count: int = 190,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._source = source
        self._automatic_updates_enabled = automatic_updates_enabled
        self._clock = clock
        self._minimum_country_count = minimum_country_count
        self._lock = asyncio.Lock()

    def status(self) -> CountryCatalogUpdateStatus:
        return _deserialize_status(
            self._store.read_status(),
            catalog=self._catalog,
            automatic_updates_enabled=self._automatic_updates_enabled,
        )

    async def update(
        self, trigger: CountryCatalogUpdateTrigger
    ) -> CountryCatalogUpdateStatus:
        now = _aware_utc(self._clock())
        if self._lock.locked() or not self._store.acquire_lease(now):
            current = self.status()
            return _replace_status(
                current,
                state=CountryCatalogUpdateState.RUNNING,
                trigger=trigger,
                message="A country catalog update is already running.",
            )
        async with self._lock:
            previous = self.status()
            running = _replace_status(
                previous,
                state=CountryCatalogUpdateState.RUNNING,
                trigger=trigger,
                last_attempt_at=now,
                message="Fetching and validating autonomous country metadata.",
                failure_code=None,
            )
            try:
                self._write_status(running)
            except Exception:
                self._store.release_lease()
                raise
            try:
                snapshot = await self._source.fetch()
                payload = build_country_catalog_payload(
                    snapshot, minimum_country_count=self._minimum_country_count
                )
                serialized = serialize_country_catalog(payload)
                metadata = _json_object(payload.get("metadata"))
                version = _required_string(metadata, "version")
                countries = cast(list[object], payload["countries"])
                sources = _source_versions(snapshot)
                if version == previous.active_version:
                    completed = CountryCatalogUpdateStatus(
                        state=CountryCatalogUpdateState.UNCHANGED,
                        active_version=version,
                        country_count=len(countries),
                        automatic_updates_enabled=self._automatic_updates_enabled,
                        trigger=trigger,
                        last_attempt_at=now,
                        last_success_at=now,
                        message=(
                            f"Catalog {version} is already active with "
                            f"{len(countries)} countries."
                        ),
                        sources=sources,
                    )
                else:
                    self._store.promote(payload, serialized)
                    completed = CountryCatalogUpdateStatus(
                        state=CountryCatalogUpdateState.UPDATED,
                        active_version=version,
                        country_count=len(countries),
                        automatic_updates_enabled=self._automatic_updates_enabled,
                        trigger=trigger,
                        last_attempt_at=now,
                        last_success_at=now,
                        message=(
                            f"Promoted catalog {version} with {len(countries)} "
                            "countries after all validation gates passed."
                        ),
                        sources=sources,
                    )
            except Exception as error:
                _LOGGER.exception("Autonomous country catalog update failed closed")
                completed = CountryCatalogUpdateStatus(
                    state=CountryCatalogUpdateState.FAILED,
                    active_version=previous.active_version,
                    country_count=previous.country_count,
                    automatic_updates_enabled=self._automatic_updates_enabled,
                    trigger=trigger,
                    last_attempt_at=now,
                    last_success_at=previous.last_success_at,
                    message=(
                        "Catalog update failed closed; the previous version remains "
                        "active and the scheduler will retry automatically."
                    ),
                    failure_code=_failure_code(error),
                    sources=previous.sources,
                )
            finally:
                self._store.release_lease()
            self._write_status(completed)
            return completed

    def _write_status(self, status: CountryCatalogUpdateStatus) -> None:
        self._store.write_status(_serialize_status(status))

    async def aclose(self) -> None:
        await self._source.aclose()


class CountryCatalogAutomation:
    """Run manual updates and catch-up-safe monthly UTC scheduling."""

    def __init__(
        self,
        updater: AutonomousCountryCatalogUpdater,
        *,
        automatic_updates_enabled: bool,
        retry_interval: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._updater = updater
        self._automatic_updates_enabled = automatic_updates_enabled
        self._retry_interval = retry_interval
        self._clock = clock
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def status(self) -> CountryCatalogUpdateStatus:
        current = self._updater.status()
        next_scheduled = (
            next_country_catalog_update_at(
                current,
                now=_aware_utc(self._clock()),
                retry_interval=self._retry_interval,
            )
            if self._automatic_updates_enabled
            else None
        )
        return _replace_status(current, next_scheduled_at=next_scheduled)

    async def request_update(
        self, trigger: CountryCatalogUpdateTrigger
    ) -> CountryCatalogUpdateStatus:
        await self._updater.update(trigger)
        return self.status()

    async def start(self) -> None:
        if not self._automatic_updates_enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(), name="country-catalog-monthly-updater"
        )

    async def _run(self) -> None:
        while not self._stop.is_set():
            current = self.status()
            now = _aware_utc(self._clock())
            due = current.next_scheduled_at
            if due is not None and due <= now:
                result = await self._updater.update(
                    CountryCatalogUpdateTrigger.SCHEDULED
                )
                current = self.status()
                now = _aware_utc(self._clock())
                due = (
                    now + timedelta(minutes=1)
                    if result.state == CountryCatalogUpdateState.RUNNING
                    else current.next_scheduled_at
                )
            delay = 3600.0
            if due is not None:
                delay = max(1.0, min(delay, (due - now).total_seconds()))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                continue

    async def aclose(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        await self._updater.aclose()


def next_country_catalog_update_at(
    status: CountryCatalogUpdateStatus,
    *,
    now: datetime,
    retry_interval: timedelta,
) -> datetime:
    """Return first-of-month due time or a bounded retry after failure."""
    current = _aware_utc(now)
    month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if status.last_success_at is not None and status.last_success_at >= month_start:
        return _next_month(month_start)
    if (
        status.state == CountryCatalogUpdateState.FAILED
        and status.last_attempt_at is not None
        and status.last_attempt_at >= month_start
    ):
        return status.last_attempt_at + retry_interval
    return month_start


def _failure_code(error: Exception) -> str:
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return "upstream_timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return "upstream_http_error"
    if isinstance(error, ValueError):
        return "validation_failed"
    if isinstance(error, OSError):
        return "storage_failure"
    return "update_failed"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Country catalog automation requires timezone-aware time.")
    return value.astimezone(UTC)


def _next_month(month_start: datetime) -> datetime:
    if month_start.month == 12:
        return month_start.replace(year=month_start.year + 1, month=1)
    return month_start.replace(month=month_start.month + 1)
