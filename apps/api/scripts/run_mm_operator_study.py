"""Score legitimate paired human/operator MM-C results; never simulate them."""

import argparse
import json
from pathlib import Path
from typing import Any

from disaster_monitor.evaluation.operator_study import (
    OperatorStudyError,
    score_operator_study,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--protocol", type=Path)
    arguments = parser.parse_args()
    protocol_path = arguments.protocol or (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "evaluation"
        / "fixtures"
        / "multimodal"
        / "operator_study_protocol.v1.json"
    )
    try:
        protocol = _read_json(protocol_path)
        results = _read_json(arguments.results)
        score = score_operator_study(protocol, results)
    except (OSError, ValueError, OperatorStudyError) as error:
        payload = {
            "status": "blocked_or_failed",
            "passed": False,
            "error": str(error),
            "protocol": str(protocol_path.resolve()),
            "results": str(arguments.results.resolve()),
        }
        _emit(payload, arguments.output)
        print(f"MM-C operator gate failed closed: {error}")
        return 2
    payload = score.to_dict()
    payload["status"] = "passed" if score.passed else "failed"
    _emit(payload, arguments.output)
    print(
        "MM-C operator comparison: "
        f"text-only={score.text_only.completion_rate:.3f}; "
        f"COP={score.cop.completion_rate:.3f}; "
        f"absolute improvement={score.absolute_task_completion_improvement:.3f}; "
        f"participants={score.participant_count}; "
        f"gate={'PASS' if score.passed else 'FAIL'}"
    )
    return 0 if score.passed else 1


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise OperatorStudyError(
            f"required operator-study JSON is absent: {path.resolve()}"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


def _emit(payload: dict[str, Any], output: Path | None) -> None:
    encoded = json.dumps(payload, indent=2) + "\n"
    if output is None:
        print(encoded, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    print(f"Machine-readable operator result: {output.resolve()}")


if __name__ == "__main__":
    raise SystemExit(main())
