"""Record a reproducible baseline or experiment identity from actual local state."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from disaster_monitor.evaluation.reproducibility import (
    ReproducibilityError,
    build_experiment_record,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--experiment-id")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--gate-result", default="recorded")
    parser.add_argument("--require-clean", action="store_true")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    experiment_id = arguments.experiment_id or (
        datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") + "-stage3-baseline"
    )
    command = [
        "uv",
        "run",
        "--directory",
        "apps/api",
        "python",
        "scripts/record_experiment_baseline.py",
        "--output",
        str(arguments.output),
    ]
    try:
        record = build_experiment_record(
            repository_root=root,
            experiment_id=experiment_id,
            command=command,
            manifest_path=arguments.manifest,
            evaluator_version="dm-experiment-recorder-v1",
            gate_result=arguments.gate_result,
        )
        if arguments.require_clean and record["git"]["dirty"]:
            raise ReproducibilityError("A release baseline requires a clean worktree")
        output = arguments.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    except (OSError, ReproducibilityError, ValueError) as error:
        print(f"Experiment baseline recording failed closed: {error}")
        return 2
    print(f"Experiment identity recorded at {output} ({record['record_sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
