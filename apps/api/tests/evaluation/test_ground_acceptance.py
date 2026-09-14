import json
from datetime import date
from pathlib import Path

from disaster_monitor.evaluation.ground_acceptance import (
    GroundAcceptanceManifest,
    live_evidence_status,
    resource_gate,
)


def test_live_evidence_requires_every_declared_case(tmp_path: Path) -> None:
    manifest = tmp_path / "ground.json"
    manifest.write_text(
        json.dumps(
            {
                "live_evidence": [
                    {"case_id": "case-one", "status": "passed"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = live_evidence_status(
        manifest,
        required_case_ids=frozenset({"case-one", "case-two"}),
    )

    assert result["status"] == "pending"
    assert result["missing_case_ids"] == ["case-two"]


def test_resource_gate_accepts_normal_reserved_memory_on_16_gb_host() -> None:
    manifest = GroundAcceptanceManifest(
        version="fixture",
        retrieval_date=date(2026, 9, 14),
        target_gpu_name="RTX 3050 Ti",
        target_gpu_memory_mb=4096,
        target_system_memory_gb=16,
        cases=(),
    )

    result = resource_gate(
        manifest,
        {
            "system_memory_gb": 15.9,
            "gpus": [
                {"name": "NVIDIA GeForce RTX 3050 Ti Laptop GPU", "memory_mb": 4096}
            ],
        },
    )

    assert result["status"] == "pass"
    assert result["minimum_observed_memory_gb"] == 15.2
