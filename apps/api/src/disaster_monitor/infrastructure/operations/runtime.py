"""Minimal PostgreSQL scheduler/worker processes for production-like Compose."""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
from datetime import UTC, datetime

from disaster_monitor.application.services.operational_ingestion import (
    IngestionScheduler,
    ScheduledInvestigation,
    ScheduledInvestigationWorker,
)
from disaster_monitor.infrastructure.composition import (
    build_country_catalog,
    build_current_disaster_report,
    build_operational_services,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)


def scheduled_investigations(
    settings: Settings | None = None,
) -> tuple[ScheduledInvestigation, ...]:
    """Return no recurring jobs until worldwide scheduling is explicitly modeled."""
    return ()


def _postgres(settings: Settings) -> PostgresOperationalRepository:
    if settings.operational_database_url is None:
        raise RuntimeError(
            "OPERATIONAL_DATABASE_URL is required for scheduler and worker processes."
        )
    return PostgresOperationalRepository(
        settings.operational_database_url.get_secret_value()
    )


async def _migrate(settings: Settings) -> None:
    await _postgres(settings).migrate()


async def _scheduler(settings: Settings, *, once: bool) -> None:
    repository = _postgres(settings)
    scheduler = IngestionScheduler(repository, scheduled_investigations(settings))
    while True:
        await scheduler.enqueue_due(now=datetime.now(UTC))
        if once:
            return
        await asyncio.sleep(30)


async def _worker(settings: Settings, *, once: bool) -> None:
    repository = _postgres(settings)
    operational = build_operational_services(settings, repository)
    countries = build_country_catalog(settings)
    report = build_current_disaster_report(
        settings,
        countries,
        snapshot_recorder=operational.snapshots.persist,
        operational_evidence=operational.evidence,
    )
    worker = ScheduledInvestigationWorker(
        repository,
        report,
        scheduled_investigations(settings),
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    try:
        while True:
            job = await worker.run_once(worker_id)
            if once:
                return
            if job is None:
                await asyncio.sleep(2)
    finally:
        await report.aclose()


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("migrate", "scheduler", "worker"))
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    settings = Settings()
    if arguments.command == "migrate":
        asyncio.run(_migrate(settings))
    elif arguments.command == "scheduler":
        asyncio.run(_scheduler(settings, once=arguments.once))
    else:
        asyncio.run(_worker(settings, once=arguments.once))


if __name__ == "__main__":
    run()
