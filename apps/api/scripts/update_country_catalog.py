"""Run or inspect the autonomous global country catalog update process."""

from __future__ import annotations

import argparse
import asyncio
import json

from disaster_monitor.application.ports.geography import (
    CountryCatalogUpdateState,
    CountryCatalogUpdateStatus,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.infrastructure.composition import (
    build_country_catalog,
    build_country_catalog_automation,
)
from disaster_monitor.infrastructure.configuration import Settings


def _payload(status: CountryCatalogUpdateStatus) -> dict[str, object]:
    return {
        "state": status.state.value,
        "active_version": status.active_version,
        "country_count": status.country_count,
        "automatic_updates_enabled": status.automatic_updates_enabled,
        "trigger": status.trigger.value if status.trigger else None,
        "last_attempt_at": (
            status.last_attempt_at.isoformat() if status.last_attempt_at else None
        ),
        "last_success_at": (
            status.last_success_at.isoformat() if status.last_success_at else None
        ),
        "next_scheduled_at": (
            status.next_scheduled_at.isoformat() if status.next_scheduled_at else None
        ),
        "message": status.message,
        "failure_code": status.failure_code,
        "sources": [
            {
                "source_id": source.source_id,
                "version": source.version,
                "revision": source.revision,
                "sha256": source.sha256,
            }
            for source in status.sources
        ],
    }


async def _run(*, status_only: bool) -> CountryCatalogUpdateStatus:
    settings = Settings()
    catalog = build_country_catalog(settings)
    automation = build_country_catalog_automation(settings, catalog)
    try:
        if status_only:
            return automation.status()
        return await automation.request_update(CountryCatalogUpdateTrigger.SCRIPT)
    finally:
        await automation.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--status",
        action="store_true",
        help="Read local status without contacting upstream sources.",
    )
    arguments = parser.parse_args()
    result = asyncio.run(_run(status_only=arguments.status))
    print(json.dumps(_payload(result), ensure_ascii=False, indent=2))
    if result.state == CountryCatalogUpdateState.FAILED:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
