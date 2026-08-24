import json
import subprocess
import sys
from pathlib import Path

import pytest

from disaster_monitor.application.services.specialist_executor import (
    SpecialistExecutionResult,
)
from disaster_monitor.evaluation.disaster_agent_bench import (
    DisasterAgentBenchError,
    ReplayMode,
    evaluate_integrity,
    lock_selection,
    replay_episode,
    summarize_specialist_benchmark,
    validate_locked_manifest,
)
from disaster_monitor.evaluation.reproducibility import (
    canonical_json_sha256,
    file_sha256,
)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _locked_bundle(tmp_path: Path) -> tuple[Path, Path]:
    rights = tmp_path / "rights" / "global-warnings.json"
    _write_json(
        rights,
        {
            "source_id": "global-warnings-rss",
            "use_basis": "test-fixture-only",
            "redistribution": "not-applicable",
        },
    )
    episode_root = tmp_path / "episodes" / "vnm-flood-1"
    first_payload = episode_root / "payloads" / "revision-1.xml"
    second_payload = episode_root / "payloads" / "revision-2.xml"
    first_payload.parent.mkdir(parents=True)
    first_payload.write_text("<alert>first</alert>", encoding="utf-8")
    second_payload.write_text("<alert>second</alert>", encoding="utf-8")
    request_hash = "sha256:" + "1" * 64
    snapshots = {
        "schema_version": "dm.source-snapshots.v1",
        "snapshots": [
            {
                "snapshot_id": "snapshot-late-retrieval",
                "source_id": "global-warnings-rss",
                "provider_record_id": "bulletin-1",
                "retrieved_at": "2026-08-02T03:00:00+00:00",
                "published_at": "2026-08-02T01:00:00+00:00",
                "observed_at": None,
                "request_fingerprint": request_hash,
                "payload_relpath": "payloads/revision-1.xml",
                "payload_sha256": file_sha256(first_payload),
                "content_type": "application/xml",
                "parser_version": "global-warnings-rss-v1",
                "rights_ref": "rights/global-warnings.json",
            },
            {
                "snapshot_id": "snapshot-early-retrieval",
                "source_id": "global-warnings-rss",
                "provider_record_id": "bulletin-1",
                "retrieved_at": "2026-08-02T02:00:00+00:00",
                "published_at": "2026-08-02T02:30:00+00:00",
                "observed_at": None,
                "request_fingerprint": request_hash,
                "payload_relpath": "payloads/revision-2.xml",
                "payload_sha256": file_sha256(second_payload),
                "content_type": "application/xml",
                "parser_version": "global-warnings-rss-v1",
                "rights_ref": "rights/global-warnings.json",
            },
        ],
    }
    snapshot_manifest = episode_root / "snapshots.json"
    _write_json(snapshot_manifest, snapshots)
    hidden = tmp_path / "release-labels" / "vnm-flood-1.json"
    _write_json(hidden, {"episode_id": "vnm-flood-1", "outcome": "hidden"})
    episode = {
        "episode_id": "vnm-flood-1",
        "disaster": "flood",
        "country_code": "VNM",
        "time_window": {
            "start": "2026-08-02T00:00:00+00:00",
            "end": "2026-08-03T00:00:00+00:00",
        },
        "source_snapshot_manifest": "episodes/vnm-flood-1/snapshots.json",
        "source_snapshot_manifest_sha256": file_sha256(snapshot_manifest),
        "hidden_labels_ref": "release-labels/vnm-flood-1.json",
        "hidden_labels_sha256": file_sha256(hidden),
    }
    selection = {
        "schema_version": "dm.disasteragentbench-selection.v1",
        "manifest_id": "dab-test-release",
        "created_from_commit": "a" * 40,
        "created_at_utc": "2026-08-13T00:00:00+00:00",
        "episodes": [episode],
    }
    selection_path = tmp_path / "selection.json"
    _write_json(selection_path, selection)
    manifest = lock_selection(tmp_path, selection_path)
    manifest_path = tmp_path / "locked-release-manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path, second_payload


def test_lock_validate_and_integrity_replay_keep_hidden_labels_out_of_runtime(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _locked_bundle(tmp_path)

    manifest, episodes = validate_locked_manifest(manifest_path)
    result = evaluate_integrity(manifest_path)

    assert manifest["manifest_sha256"] == canonical_json_sha256(
        manifest, exclude_top_level=frozenset({"manifest_sha256"})
    )
    assert len(episodes) == 1
    assert not hasattr(episodes[0], "hidden_labels_ref")
    assert result.integrity_passed
    assert result.deterministic_replay
    assert result.hidden_labels_separated
    assert not result.normative_release_passed
    assert result.normative_release_blockers


def test_operational_and_canonical_replay_orders_differ_but_final_state_matches(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _locked_bundle(tmp_path)
    _, episodes = validate_locked_manifest(manifest_path)

    operational = replay_episode(episodes[0], ReplayMode.ORIGINAL_INGESTION_ORDER)
    canonical = replay_episode(episodes[0], ReplayMode.CANONICAL_EFFECTIVE_TIME)

    assert operational.ordered_snapshot_ids != canonical.ordered_snapshot_ids
    assert operational.source_set_hash == canonical.source_set_hash
    assert operational.canonical_state_hash == canonical.canonical_state_hash


def test_locked_bundle_fails_closed_when_payload_changes(tmp_path: Path) -> None:
    manifest_path, payload = _locked_bundle(tmp_path)
    payload.write_text("<alert>tampered</alert>", encoding="utf-8")

    with pytest.raises(DisasterAgentBenchError, match="payload"):
        validate_locked_manifest(manifest_path)


def test_locked_bundle_rejects_manifest_whitespace_independent_hash_change(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _locked_bundle(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_id"] = "changed-after-lock"
    _write_json(manifest_path, manifest)

    with pytest.raises(DisasterAgentBenchError, match="canonical hash"):
        validate_locked_manifest(manifest_path)


def test_run_cli_writes_fail_closed_result_for_invalid_manifest(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "invalid-manifest.json"
    output = tmp_path / "result.json"
    _write_json(manifest, {"manifest_sha256": "replace-me"})
    script = Path(__file__).parents[2] / "scripts" / "run_disaster_agent_bench.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 2
    assert "failed closed" in completed.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == (
        "blocked_or_failed"
    )


def test_specialist_benchmark_records_safety_and_runtime_metrics() -> None:
    runs = (
        SpecialistExecutionResult((), 2, None, 0, 12.5),
        SpecialistExecutionResult((), 1, "evidence_membership_violation", 1, 7.5),
    )

    metrics = summarize_specialist_benchmark(
        runs,
        correctness=(True, False),
        grounding=(True, False),
    )

    assert metrics.correctness == 0.5
    assert metrics.grounding == 0.5
    assert metrics.provenance_validation_failures == 1
    assert metrics.fallback_rate == 0.5
    assert metrics.specialist_model_call_count == 3
    assert metrics.average_latency_ms == 10.0
