"""Validate and lock externally staged MM benchmark slices."""

import hashlib
import json
from pathlib import Path
from typing import Any

FAMILIES = {"xBD", "FloodNet", "DisasterInsight", "DM-held-out"}
TASKS = {"damage_classification", "visual_question_answering", "association"}
DAMAGE_CLASSES = {
    "no_visible_damage",
    "minor_damage",
    "major_damage",
    "destroyed",
}
ASSOCIATION_STATUSES = {"associated", "ambiguous", "unmatched", "orphaned"}


def lock_manifest(
    staged_root: Path,
    selection_file: Path,
    *,
    specification_path: Path | None = None,
) -> dict[str, Any]:
    root = staged_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    if selection.get("manifest_version") != "dm-mm-locked-v1":
        raise ValueError("selection manifest_version must be dm-mm-locked-v1")
    samples = selection.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("the locked release selection requires non-empty samples")
    development_ids = set(selection.get("development_sample_ids", []))
    seen_ids: set[str] = set()
    seen_families: set[str] = set()
    normalized = []
    for raw in samples:
        if not isinstance(raw, dict):
            raise ValueError("each locked sample must be an object")
        sample = _validated_sample(raw, root)
        sample_id = sample["sample_id"]
        if sample_id in seen_ids or sample_id in development_ids:
            raise ValueError("held-out sample IDs must be unique and development-free")
        seen_ids.add(sample_id)
        seen_families.add(sample["dataset_family"])
        normalized.append(sample)
    if seen_families != FAMILIES:
        raise ValueError(
            "locked samples must include xBD, FloodNet, DisasterInsight, "
            "and DM-held-out"
        )
    damage_classes = {
        item["expected_damage"]
        for item in normalized
        if item["task"] == "damage_classification"
    }
    if damage_classes != DAMAGE_CLASSES:
        raise ValueError("locked damage samples must cover every frozen class")
    vqa_coverage = {
        "prohibited"
        if item.get("prohibited") is True
        else "answerable"
        if item.get("answerable") is True
        else "unanswerable"
        for item in normalized
        if item["task"] == "visual_question_answering"
    }
    if vqa_coverage != {"answerable", "unanswerable", "prohibited"}:
        raise ValueError(
            "locked VQA samples must cover answerable, unanswerable, "
            "and prohibited cases"
        )
    statuses = {item["expected_association"] for item in normalized}
    if statuses != ASSOCIATION_STATUSES:
        raise ValueError("locked association samples must cover every frozen status")
    specification = specification_path or (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "evaluation"
        / "fixtures"
        / "multimodal"
        / "benchmark_spec.v1.json"
    )
    return {
        "manifest_version": "dm-mm-locked-v1",
        "specification_sha256": _sha256(specification),
        "prompt_version": "dm-visual-analysis-v1",
        "preprocessing_version": "original-png-jpeg-bytes-v1",
        "frozen_baseline": "constant-no-visible-damage-v1",
        "development_sample_ids": sorted(development_ids),
        "samples": sorted(normalized, key=lambda item: item["sample_id"]),
    }


def _validated_sample(raw: dict[str, Any], root: Path) -> dict[str, Any]:
    required = {
        "sample_id",
        "dataset_family",
        "dataset_version",
        "split",
        "task",
        "relative_path",
        "source_id",
        "attribution",
        "captured_at",
        "capture_role",
        "disaster",
        "country_code",
        "footprint",
        "event",
        "expected_association",
        "expected_geography_match",
        "expected_time_match",
        "license_or_dataset_identity",
    }
    if not required.issubset(raw):
        raise ValueError(f"sample is missing fields: {sorted(required - set(raw))}")
    if raw["dataset_family"] not in FAMILIES or raw["task"] not in TASKS:
        raise ValueError("sample dataset family or task is outside the frozen mapping")
    if raw["split"] != "held_out":
        raise ValueError("release samples must use the held_out split")
    if raw["expected_association"] not in ASSOCIATION_STATUSES:
        raise ValueError("sample association label is outside the frozen mapping")
    if (
        raw["task"] == "damage_classification"
        and raw.get("expected_damage") not in DAMAGE_CLASSES
    ):
        raise ValueError("damage samples require one frozen damage class")
    if raw["task"] == "visual_question_answering":
        if not isinstance(raw.get("answerable"), bool) or not isinstance(
            raw.get("question"), str
        ):
            raise ValueError(
                "VQA samples require question, answerable, and expected-answer metadata"
            )
        if raw["answerable"] and not isinstance(raw.get("expected_answer"), str):
            raise ValueError("answerable VQA samples require an expected answer")
    relative = Path(raw["relative_path"])
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise ValueError(
            f"staged sample path is absent or escapes the root: {relative}"
        )
    checksum = _sha256(candidate)
    supplied_checksum = raw.get("sha256")
    if supplied_checksum is not None and supplied_checksum != checksum:
        raise ValueError(f"checksum mismatch for {raw['sample_id']}")
    sample = dict(raw)
    sample["sha256"] = checksum
    return sample


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
