"""One bounded real HTTP discovery run, with retained evidence and a failure funnel.

Start the normal API manually first. Never pass reference URLs or fixture identities.
This command is a live evaluation, not a load test. It preserves incomplete results.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

import httpx


async def evaluate(base: str, days: int, output: Path) -> dict[str, Any]:
    started = monotonic()
    async with httpx.AsyncClient(base_url=base, timeout=30, trust_env=False) as client:
        response = await client.post("/discovery-scans", json={"reporting_days": days})
        response.raise_for_status()
        scan = response.json()
        observations: list[dict[str, Any]] = []
        while True:
            result = {
                "kind": "live application HTTP scan; no reference preloading",
                "observed_at": datetime.now(UTC).isoformat(),
                "elapsed_seconds": round(monotonic() - started, 2),
                "scan": scan,
                "progress": observations,
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            if scan["status"] != "running" or monotonic() - started > 240:
                break
            observations.append(
                {
                    "elapsed_seconds": round(monotonic() - started, 2),
                    "reports": scan["reports_seen"],
                    "events": len(scan["snapshot"]["incidents"]),
                }
            )
            await asyncio.sleep(3)
            response = await client.get(f"/discovery-scans/{scan['scan_id']}")
            response.raise_for_status()
            scan = response.json()
        print(
            json.dumps(
                {
                    "scan_id": scan["scan_id"],
                    "status": scan["status"],
                    "reports": scan["reports_seen"],
                    "events": len(scan["snapshot"]["incidents"]),
                    "assessment_counts": scan.get("assessment_counts"),
                    "elapsed_seconds": result["elapsed_seconds"],
                },
                indent=2,
            )
        )
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8787/api/v1")
    parser.add_argument("--days", type=int, choices=(1, 3, 7, 14, 30), default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(evaluate(args.base, args.days, args.output))


if __name__ == "__main__":
    main()
