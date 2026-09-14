"""Validate Ground acceptance evidence and report local resource readiness."""

import argparse
import json
from datetime import date
from pathlib import Path

from disaster_monitor.evaluation.ground_acceptance import (
    collect_resource_measurement,
    live_evidence_status,
    load_ground_acceptance,
    resource_gate,
)
from disaster_monitor.evaluation.reproducibility import ReproducibilityError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPOSITORY_ROOT / "evaluation" / "ground_acceptance.v1.json",
    )
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    manifest_path = arguments.manifest.resolve()
    try:
        manifest = load_ground_acceptance(manifest_path, today=date.today())
        resources = collect_resource_measurement()
        resource_result = resource_gate(manifest, resources)
        live_result = live_evidence_status(
            manifest_path,
            required_case_ids=frozenset(item.case_id for item in manifest.cases),
            declared_statuses={
                item.case_id: item.live_status for item in manifest.cases
            },
        )
    except (OSError, ReproducibilityError, ValueError) as error:
        print(f"Ground acceptance failed closed: {error}")
        return 2
    promotion_status = (
        "passed"
        if resource_result["status"] == "pass" and live_result["status"] == "passed"
        else "pending"
    )
    report = {
        "manifest_version": manifest.version,
        "manifest_valid": True,
        "cases": [
            {
                "case_id": item.case_id,
                "sensor": item.sensor,
                "event_label": item.event_label,
                "live_status": item.live_status,
                "evidence_checksum": item.evidence_checksum,
                "expected_ui_results": list(item.expected_ui_results),
            }
            for item in manifest.cases
        ],
        "resources": resources,
        "resource_gate": resource_result,
        "live_evidence": live_result,
        "promotion_status": promotion_status,
        "scope_note": (
            "This gate validates the declared Ground acceptance evidence only. "
            "It does not establish damage-assessment accuracy or global imagery "
            "coverage."
        ),
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.resolve().write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if arguments.require_live and promotion_status != "passed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
