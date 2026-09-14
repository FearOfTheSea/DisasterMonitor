"""Validation and local resource measurement for Ground-view acceptance evidence."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from disaster_monitor.evaluation.reproducibility import (
    ReproducibilityError,
    canonical_json_sha256,
    read_json_object,
    require_aware_timestamp,
    require_sha256,
)

SUPPORTED_SENSORS = frozenset({"sentinel-1", "sentinel-2"})


@dataclass(frozen=True, slots=True)
class GroundAcceptanceCase:
    case_id: str
    sensor: str
    event_label: str
    event_from: datetime
    event_to: datetime
    capture_from: datetime
    capture_to: datetime
    source_urls: tuple[str, ...]
    independent_verification_urls: tuple[str, ...]
    expected_ui_results: tuple[str, ...]
    evidence_checksum: str
    live_status: str


@dataclass(frozen=True, slots=True)
class GroundAcceptanceManifest:
    version: str
    retrieval_date: date
    target_gpu_name: str
    target_gpu_memory_mb: int
    target_system_memory_gb: int
    cases: tuple[GroundAcceptanceCase, ...]


def load_ground_acceptance(
    path: Path, *, today: date | None = None
) -> GroundAcceptanceManifest:
    """Load a study-local acceptance manifest without downloading remote media."""
    document = read_json_object(path.resolve(), "Ground acceptance manifest")
    if document.get("schema_version") != "ground-acceptance.v1":
        raise ReproducibilityError("Unsupported Ground acceptance schema version.")
    retrieval_date_value = document.get("retrieval_date")
    if not isinstance(retrieval_date_value, str):
        raise ReproducibilityError("Ground acceptance retrieval_date is required.")
    try:
        retrieval_date = date.fromisoformat(retrieval_date_value)
    except ValueError as error:
        raise ReproducibilityError(
            "Ground acceptance retrieval_date is invalid."
        ) from error
    if today is not None and retrieval_date > today:
        raise ReproducibilityError("Ground acceptance retrieval_date is in the future.")
    target = document.get("resource_target")
    if not isinstance(target, dict):
        raise ReproducibilityError("Ground acceptance resource_target is required.")
    target_gpu_name = _required_text(target, "gpu_name")
    target_gpu_memory_mb = _required_positive_int(target, "gpu_memory_mb")
    target_system_memory_gb = _required_positive_int(target, "system_memory_gb")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ReproducibilityError("Ground acceptance must contain cases.")
    cases = tuple(_case(value, retrieval_date) for value in raw_cases)
    if len({item.case_id for item in cases}) != len(cases):
        raise ReproducibilityError("Ground acceptance case IDs must be unique.")
    sensors = {item.sensor for item in cases}
    if sensors != SUPPORTED_SENSORS:
        missing = ", ".join(sorted(SUPPORTED_SENSORS - sensors))
        raise ReproducibilityError(
            "Ground acceptance must cover both sensors"
            + (f"; missing {missing}" if missing else ".")
        )
    for sensor in SUPPORTED_SENSORS:
        if sum(item.sensor == sensor for item in cases) < 2:
            raise ReproducibilityError(
                f"Ground acceptance requires two cases for {sensor}."
            )
    return GroundAcceptanceManifest(
        version=_required_text(document, "version"),
        retrieval_date=retrieval_date,
        target_gpu_name=target_gpu_name,
        target_gpu_memory_mb=target_gpu_memory_mb,
        target_system_memory_gb=target_system_memory_gb,
        cases=cases,
    )


def collect_resource_measurement() -> dict[str, Any]:
    """Measure local resources and report unknown hardware as unknown, never as pass."""
    system_memory_bytes = _system_memory_bytes()
    gpus = _nvidia_smi_gpus()
    return {
        "system_memory_bytes": system_memory_bytes,
        "system_memory_gb": (
            round(system_memory_bytes / 1_000_000_000, 2)
            if system_memory_bytes is not None
            else None
        ),
        "gpus": gpus,
        "nvidia_smi_available": shutil.which("nvidia-smi") is not None,
    }


def resource_gate(
    manifest: GroundAcceptanceManifest, measurement: dict[str, Any]
) -> dict[str, Any]:
    """Compare observed resources to the target while preserving missing evidence."""
    memory_gb = measurement.get("system_memory_gb")
    minimum_observed_memory_gb = manifest.target_system_memory_gb * 0.95
    memory_ok = (
        isinstance(memory_gb, (int, float)) and memory_gb >= minimum_observed_memory_gb
    )
    gpus = measurement.get("gpus")
    gpu_match = False
    if isinstance(gpus, list):
        for gpu in gpus:
            if not isinstance(gpu, dict):
                continue
            name = str(gpu.get("name", ""))
            memory_mb = gpu.get("memory_mb")
            if (
                manifest.target_gpu_name.casefold() in name.casefold()
                and isinstance(memory_mb, int)
                and memory_mb >= manifest.target_gpu_memory_mb
            ):
                gpu_match = True
                break
    observed = memory_gb is not None and isinstance(gpus, list) and bool(gpus)
    return {
        "status": "pass" if observed and memory_ok and gpu_match else "pending",
        "minimum_observed_memory_gb": round(minimum_observed_memory_gb, 2),
        "memory_requirement_met": memory_ok if memory_gb is not None else None,
        "gpu_requirement_met": gpu_match if isinstance(gpus, list) else None,
        "detail": (
            "Observed resources meet the declared target."
            if observed and memory_ok and gpu_match
            else "Resource evidence is incomplete or below the declared target."
        ),
    }


def live_evidence_status(
    path: Path,
    *,
    required_case_ids: frozenset[str] = frozenset(),
    declared_statuses: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return explicit live-run status without treating fixtures as runs."""
    document = read_json_object(path.resolve(), "Ground acceptance manifest")
    value = document.get("live_evidence", [])
    if not isinstance(value, list):
        raise ReproducibilityError("Ground acceptance live_evidence must be a list.")
    statuses: list[str] = []
    case_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ReproducibilityError(
                "Ground acceptance live evidence must be objects."
            )
        status = item.get("status")
        if status not in {"passed", "failed", "not_run"}:
            raise ReproducibilityError(
                "Ground acceptance live evidence status must be passed, failed, "
                "or not_run."
            )
        statuses.append(status)
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ReproducibilityError(
                "Ground acceptance live evidence needs a case_id."
            )
        if case_id in case_ids:
            raise ReproducibilityError(f"Duplicate Ground live evidence: {case_id}")
        case_ids.add(case_id)
        if declared_statuses is not None and declared_statuses.get(case_id) != status:
            raise ReproducibilityError(
                f"Ground live evidence disagrees with case status: {case_id}"
            )
    unknown = case_ids - required_case_ids
    if unknown:
        raise ReproducibilityError(
            "Ground live evidence references unknown cases: "
            + ", ".join(sorted(unknown))
        )
    missing = sorted(required_case_ids - case_ids)
    if not statuses:
        return {
            "status": "pending",
            "records": 0,
            "missing_case_ids": sorted(required_case_ids),
        }
    if any(status == "failed" for status in statuses):
        status = "failed"
    elif not missing and all(status == "passed" for status in statuses):
        status = "passed"
    else:
        status = "pending"
    return {"status": status, "records": len(statuses), "missing_case_ids": missing}


def _case(value: object, retrieval_date: date) -> GroundAcceptanceCase:
    if not isinstance(value, dict):
        raise ReproducibilityError("Ground acceptance cases must be objects.")
    case_id = _required_text(value, "case_id")
    sensor = _required_text(value, "sensor")
    if sensor not in SUPPORTED_SENSORS:
        raise ReproducibilityError(f"Unsupported Ground acceptance sensor: {sensor}")
    event_from = _timestamp(value, "event_interval_utc", "from")
    event_to = _timestamp(value, "event_interval_utc", "to")
    capture_from = _timestamp(value, "capture_interval_utc", "from")
    capture_to = _timestamp(value, "capture_interval_utc", "to")
    if event_to < event_from or capture_to < capture_from:
        raise ReproducibilityError(
            f"Ground acceptance case {case_id} has reversed bounds."
        )
    retrieval_end = datetime.combine(retrieval_date, datetime.max.time(), tzinfo=UTC)
    if max(event_to, capture_to) > retrieval_end:
        raise ReproducibilityError(
            f"Ground acceptance case {case_id} is in the future."
        )
    source_urls = _https_values(value, "source_urls", case_id)
    verification_urls = _https_values(value, "independent_verification_urls", case_id)
    if len(source_urls) < 2 or len(verification_urls) < 2:
        raise ReproducibilityError(
            f"Ground acceptance case {case_id} needs two source and verification URLs."
        )
    expected = value.get("expected_ui_results")
    if not isinstance(expected, list) or not all(
        isinstance(item, str) and item.strip() for item in expected
    ):
        raise ReproducibilityError(
            f"Ground acceptance case {case_id} needs expected UI results."
        )
    checksum = require_sha256(
        value.get("evidence_checksum"), f"{case_id}.evidence_checksum"
    )
    expected_checksum = canonical_json_sha256(
        value, exclude_top_level=frozenset({"evidence_checksum"})
    )
    if checksum != expected_checksum:
        raise ReproducibilityError(
            f"Ground acceptance case checksum mismatch: {case_id}"
        )
    live_status = str(value.get("live_status", "not_run"))
    if live_status not in {"passed", "failed", "not_run"}:
        raise ReproducibilityError(
            f"Ground acceptance live_status is invalid: {case_id}"
        )
    return GroundAcceptanceCase(
        case_id=case_id,
        sensor=sensor,
        event_label=_required_text(value, "event_label"),
        event_from=event_from,
        event_to=event_to,
        capture_from=capture_from,
        capture_to=capture_to,
        source_urls=source_urls,
        independent_verification_urls=verification_urls,
        expected_ui_results=tuple(item.strip() for item in expected),
        evidence_checksum=checksum,
        live_status=live_status,
    )


def _timestamp(value: dict[str, Any], container_name: str, key: str) -> datetime:
    container = value.get(container_name)
    if not isinstance(container, dict):
        raise ReproducibilityError(f"Ground acceptance {container_name} is required.")
    return require_aware_timestamp(container.get(key), f"{container_name}.{key}")


def _https_values(value: dict[str, Any], name: str, case_id: str) -> tuple[str, ...]:
    items = value.get(name)
    if not isinstance(items, list) or not all(
        isinstance(item, str) and item.startswith("https://") for item in items
    ):
        raise ReproducibilityError(
            f"Ground acceptance {case_id}.{name} must be HTTPS URLs."
        )
    values = tuple(item.strip() for item in items)
    if len(set(values)) != len(values):
        raise ReproducibilityError(
            f"Ground acceptance {case_id}.{name} has duplicates."
        )
    return values


def _required_text(value: dict[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise ReproducibilityError(f"Ground acceptance field {name} is required.")
    return item.strip()


def _required_positive_int(value: dict[str, Any], name: str) -> int:
    item = value.get(name)
    if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
        raise ReproducibilityError(f"Ground acceptance field {name} must be positive.")
    return item


def _system_memory_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _nvidia_smi_gpus() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return []
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
        )
    except (OSError, subprocess.SubprocessError):
        return []
    gpus: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        name, separator, memory = line.partition(",")
        if not separator:
            continue
        try:
            memory_mb = int(memory.strip())
        except ValueError:
            continue
        gpus.append({"name": name.strip(), "memory_mb": memory_mb})
    return gpus


__all__ = [
    "GroundAcceptanceCase",
    "GroundAcceptanceManifest",
    "SUPPORTED_SENSORS",
    "collect_resource_measurement",
    "live_evidence_status",
    "load_ground_acceptance",
    "resource_gate",
]
