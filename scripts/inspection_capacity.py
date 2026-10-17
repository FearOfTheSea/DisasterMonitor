"""Reproducible ten-session controlled HTTP capacity test, never usability evidence."""

import argparse
import asyncio
import json
import platform
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

THRESHOLDS = {
    "request_p95_ms": 3000,
    "request_p99_ms": 10000,
    "iteration_p95_ms": 15000,
    "unexpected_errors": 0,
    "isolation_errors": 0,
}


def percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}
    return {
        f"p{p}_ms": round(
            ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p / 100))], 2
        )
        for p in (50, 95, 99)
    }


async def run(seconds: float, base: str) -> dict[str, Any]:
    durations: dict[str, list[float]] = defaultdict(list)
    statuses: Counter[str] = Counter()
    errors: list[str] = []
    isolation: list[str] = []
    expected: Counter[str] = Counter()
    iterations: list[float] = []
    imagery_ids: dict[tuple[str, int], str] = {}
    initial_scans: list[str] = []
    ready = asyncio.Event()
    started = time.perf_counter()
    began_at = datetime.now(UTC).isoformat()

    async def session(user: int) -> None:
        async with httpx.AsyncClient(
            base_url=base, timeout=30, trust_env=False
        ) as client:

            async def request(
                method: str,
                path: str,
                name: str,
                status: int | tuple[int, ...] = 200,
                body: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                before = time.perf_counter()
                response = await client.request(method, path, json=body)
                durations[name].append((time.perf_counter() - before) * 1000)
                statuses[f"{name}:{response.status_code}"] += 1
                accepted = (status,) if isinstance(status, int) else status
                if response.status_code not in accepted:
                    raise AssertionError(
                        f"{name}: expected {status}, got {response.status_code}: "
                        f"{response.text[:160]}"
                    )
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object response.")
                return payload

            await ready.wait()
            round_number = 0
            while time.perf_counter() - started < seconds:
                iteration = time.perf_counter()
                try:
                    scan = await request(
                        "POST",
                        "/discovery-scans",
                        "scan_start",
                        202,
                        {"reporting_days": 7},
                    )
                    if round_number == 0:
                        initial_scans.append(scan["scan_id"])
                    while scan["status"] == "running":
                        if time.perf_counter() - iteration > 30:
                            raise TimeoutError(
                                "Scan did not terminate within 30 seconds."
                            )
                        await asyncio.sleep(0.2)
                        scan = await request(
                            "GET", f"/discovery-scans/{scan['scan_id']}", "scan_poll"
                        )
                    events = scan["snapshot"]["incidents"]
                    assert len(events) == 8
                    event = events[(user + round_number) % len(events)]
                    identifier = event["event_id"]
                    selected = await request(
                        "GET", f"/incidents/{identifier}", "article_lookup"
                    )
                    assert selected["event_id"] == identifier
                    articles = selected["discovery_reports"]
                    dated = sorted(
                        (a for a in articles if a["source"]["published_at"]),
                        key=lambda a: a["source"]["published_at"],
                        reverse=True,
                    )
                    pages = [dated[i : i + 5] for i in range(0, len(dated), 5)]
                    assert sum(map(len, pages)) == len(dated)
                    if len(articles) > 1:
                        assert len(pages[0]) == 5 and len(pages) == 2
                        claims = [c for a in articles for c in a["claims"]]
                        assert any(c["value"] == "0" for c in claims)
                        assert not any(c["category"] == "buildings" for c in claims)
                        assert (
                            len({a["source"]["canonical_url"] for a in articles}) == 8
                        )
                    media = await request(
                        "GET", f"/incidents/{identifier}/evidence/media", "photographs"
                    )
                    assert media["evidence"]["event_id"] == identifier
                    if media["evidence"].get("media"):
                        gallery = media["evidence"]["media"]
                        assert len(gallery["items"]) == 7
                        expected["broken_photo_retained_source"] += len(
                            gallery["unavailable_sources"]
                        )
                    imagery: dict[str, Any] | None
                    if event["event_time"] is not None:
                        imagery = await request(
                            "POST",
                            "/ground-imagery/requests",
                            "imagery_search",
                            (202, 429),
                            {
                                "incident_id": identifier,
                                "owner_scope": f"capacity-{user}",
                                "idempotency_key": identifier,
                                "reference_time": "2026-10-18T00:00:00Z",
                            },
                        )
                        if "request_id" not in imagery:
                            expected["imagery_catalog_quota"] += 1
                            imagery = None
                    else:
                        expected["unresolved_time_skips_imagery"] += 1
                        imagery = None
                    if imagery is not None:
                        assert imagery["incident_id"] == identifier
                        rid = imagery["request_id"]
                        for (other_event, other_user), other_id in imagery_ids.items():
                            if (
                                other_event == identifier
                                and other_user != user
                                and other_id == rid
                            ):
                                isolation.append(
                                    f"Shared imagery request: {user}/{other_user}"
                                )
                        imagery_ids[(identifier, user)] = rid
                        expected[f"imagery_state:{imagery['state']}"] += 1
                        selection = next(
                            (
                                s
                                for sensor in imagery["sensors"]
                                for s in sensor["selections"]
                                if s["observation"]
                            ),
                            None,
                        )
                        if selection and round_number < 7:
                            prepared = await request(
                                "POST",
                                f"/ground-imagery/requests/{rid}/prepare",
                                "imagery_prepare",
                                (202, 429),
                                {
                                    "sensor": selection["sensor"],
                                    "role": selection["role"],
                                    "overview": True,
                                },
                            )
                            if "request_id" in prepared:
                                assert prepared["incident_id"] == identifier
                            else:
                                expected["imagery_render_quota"] += 1
                    await request(
                        "GET",
                        "/incidents/not-a-retained-event",
                        "expected_missing_event",
                        404,
                    )
                    if round_number % 4 == 0:
                        failed = await request(
                            "POST",
                            "/discovery-scans",
                            "failure_scan_start",
                            202,
                            {"reporting_days": 3},
                        )
                        while failed["status"] == "running":
                            if time.perf_counter() - iteration > 30:
                                raise TimeoutError(
                                    "Failure scan did not terminate within 30 seconds."
                                )
                            await asyncio.sleep(0.2)
                            failed = await request(
                                "GET",
                                f"/discovery-scans/{failed['scan_id']}",
                                "failure_scan_poll",
                            )
                        assert failed["status"] == "failed"
                        expected["failed_scan"] += 1
                    iterations.append((time.perf_counter() - iteration) * 1000)
                    round_number += 1
                    await asyncio.sleep(0.1)
                except Exception as error:
                    errors.append(f"session {user}: {type(error).__name__}: {error}")
                    await asyncio.sleep(0.5)

    tasks = [asyncio.create_task(session(i)) for i in range(10)]
    ready.set()
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - started
    all_requests = [value for group in durations.values() for value in group]
    request_stats = percentiles(all_requests)
    iteration_stats = percentiles(iterations)
    result = {
        "kind": "controlled synthetic capacity; not live or human usability evidence",
        "started_at": began_at,
        "platform": platform.platform(),
        "sessions": 10,
        "requested_duration_seconds": seconds,
        "elapsed_seconds": round(elapsed, 2),
        "thresholds": THRESHOLDS,
        "thresholds_approved_by_supervisor": False,
        "request_count": len(all_requests),
        "throughput_requests_per_second": round(len(all_requests) / elapsed, 2),
        "requests": request_stats,
        "iterations": iteration_stats,
        "iteration_count": len(iterations),
        "per_operation": {
            name: {"count": len(values), **percentiles(values)}
            for name, values in durations.items()
        },
        "statuses": dict(statuses),
        "expected_failures_and_states": dict(expected),
        "initial_compatible_scan_ids": initial_scans,
        "shared_initial_scan": len(set(initial_scans)) == 1,
        "distinct_session_imagery_requests": len(set(imagery_ids.values())),
        "unexpected_errors": errors,
        "isolation_errors": isolation,
    }
    result["passed"] = (
        not errors
        and not isolation
        and result["shared_initial_scan"]
        and request_stats.get("p95_ms", float("inf")) <= THRESHOLDS["request_p95_ms"]
        and request_stats.get("p99_ms", float("inf")) <= THRESHOLDS["request_p99_ms"]
        and iteration_stats.get("p95_ms", float("inf"))
        <= THRESHOLDS["iteration_p95_ms"]
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--base", default="http://127.0.0.1:8787/api/v1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.seconds, args.base))
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "passed",
                    "request_count",
                    "requests",
                    "iterations",
                    "unexpected_errors",
                    "isolation_errors",
                )
            },
            indent=2,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
