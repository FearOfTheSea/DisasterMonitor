"""Run the DAB integrity/replay gate and preserve external promotion blockers."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from disaster_monitor.evaluation.disaster_agent_bench import (
    evaluate_integrity,
    replay_result_payload,
)
from disaster_monitor.evaluation.reproducibility import ReproducibilityError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--integrity-only",
        action="store_true",
        help=(
            "Exit successfully after integrity/replay without claiming "
            "release promotion."
        ),
    )
    arguments = parser.parse_args()
    try:
        result = evaluate_integrity(arguments.manifest)
        payload = asdict(result)
        payload["replay_results"] = [
            replay_result_payload(item) for item in result.replay_results
        ]
        payload["status"] = (
            "integrity_passed_external_promotion_pending"
            if result.integrity_passed
            else "failed"
        )
    except (
        ReproducibilityError,
        OSError,
        ValueError,
    ) as error:
        payload = {
            "status": "blocked_or_failed",
            "integrity_passed": False,
            "normative_release_passed": False,
            "error": str(error),
        }
        _write(arguments.output, payload)
        print(f"DisasterAgentBench failed closed: {error}")
        return 2
    _write(arguments.output, payload)
    print(
        f"DAB {result.manifest_id}: integrity/replay "
        f"{'PASS' if result.integrity_passed else 'FAIL'}; normative release PENDING"
    )
    for blocker in result.normative_release_blockers:
        print(f"- {blocker}")
    if not result.integrity_passed:
        return 1
    return 0 if arguments.integrity_only else 2


def _write(path: Path, payload: dict) -> None:
    output = path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Machine-readable DAB result: {output}")


if __name__ == "__main__":
    raise SystemExit(main())
