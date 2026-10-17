"""One bounded seven-category live scan; never a deterministic acceptance test."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from disaster_monitor.application.incidents.discovery_scan import DiscoveryScanService
from disaster_monitor.infrastructure.news.discovery_feed import GdeltDiscoveryFeed
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)


async def run() -> dict[str, object]:
    calls: list[dict[str, object]] = []

    async def record(response: httpx.Response) -> None:
        calls.append(
            {
                "query": response.request.url.params.get("query"),
                "status": response.status_code,
            }
        )

    async def pace(request: httpx.Request) -> None:
        if calls:
            await asyncio.sleep(5.2)

    async with httpx.AsyncClient(
        timeout=10,
        trust_env=False,
        event_hooks={"request": [pace], "response": [record]},
    ) as client:
        feed = GdeltDiscoveryFeed(
            client=client,
            maximum_queries=7,
            maximum_records=10,
            maximum_articles=14,
            timeout_seconds=15,
        )
        with TemporaryDirectory(prefix="inspection-live-") as directory:
            service = DiscoveryScanService(
                (feed,),
                FileDiscoveryStore(Path(directory)),
                provider_timeout_seconds=50,
            )
            run = await service.start(30)
            await service.wait(run.scan_id)
            run = await service.get(run.scan_id)
            return {
                "attempted_at": datetime.now(UTC).isoformat(),
                "scan_id": run.scan_id,
                "start": run.interval.start.isoformat(),
                "end": run.interval.end.isoformat(),
                "status": run.status,
                "successful_operations": run.successful_operations,
                "failed_operations": run.failed_operations,
                "issues": run.issues,
                "events": [event.event_id for event in run.events],
                "retained_report_count": len(run.reports),
                "actual_provider_requests": calls,
                "bounds": (
                    "seven category queries, ten leads/query, fourteen article reads, "
                    "50 seconds; host cooldown stops traffic after throttling"
                ),
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run())
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
