"""Minimal PostgreSQL scheduler/worker processes for production-like Compose."""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.disaster import DisasterQuery
from disaster_monitor.application.services.operational_ingestion import (
    IngestionScheduler,
    ScheduledInvestigation,
    ScheduledInvestigationWorker,
    canonical_request_identity,
)
from disaster_monitor.domain.disaster import Hazard
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
    """Return the reviewed continuous-ingestion coverage matrix."""
    configured = settings or Settings()
    countries = build_country_catalog(configured)
    japan = countries.get_by_alpha3("JPN")
    vietnam = countries.get_by_alpha3("VNM")
    if japan is None or vietnam is None:
        raise RuntimeError("Packaged country metadata is incomplete.")
    definitions = [
        ("jma-rolling-earthquakes", Hazard.EARTHQUAKE, japan, 15, 30),
        ("nchmf-vietnam-warnings", Hazard.FLOOD, vietnam, 30, 7),
        ("nchmf-vietnam-warnings", Hazard.LANDSLIDE, vietnam, 30, 7),
        ("nchmf-vietnam-warnings", Hazard.TROPICAL_CYCLONE, vietnam, 30, 7),
    ]
    if (
        configured.firms_map_key is not None
        and configured.firms_map_key.get_secret_value().strip()
    ):
        definitions.append(("nasa-firms-active-fire", Hazard.WILDFIRE, vietnam, 180, 3))
    tasks = []
    for source_id, hazard, country, interval_minutes, window_days in definitions:
        parameters = {
            "country": country.alpha3_code,
            "hazard": hazard.value,
            "purpose": "continuous-evidence-ingestion-v1",
        }
        tasks.append(
            ScheduledInvestigation(
                source_id=source_id,
                request_identity=canonical_request_identity(source_id, parameters),
                query=DisasterQuery(
                    hazard=hazard,
                    country=country,
                    time_intent="scheduled continuous ingestion",
                    focus=("event_overview",),
                    time_window_days=window_days,
                ),
                interval=timedelta(minutes=interval_minutes),
            )
        )
    return tuple(tasks)


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
