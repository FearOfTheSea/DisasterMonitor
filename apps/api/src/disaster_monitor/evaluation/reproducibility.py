"""Canonical hashing and experiment identity helpers for release evaluation."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ReproducibilityError(RuntimeError):
    """Raised when a release identity cannot be established safely."""


def canonical_json_bytes(
    value: Mapping[str, Any], *, exclude_top_level: frozenset[str] = frozenset()
) -> bytes:
    """Encode JSON with one cross-platform canonical convention."""
    normalized = {
        key: item for key, item in value.items() if key not in exclude_top_level
    }
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json_sha256(
    value: Mapping[str, Any], *, exclude_top_level: frozenset[str] = frozenset()
) -> str:
    """Return a prefixed SHA-256 over canonical JSON bytes."""
    digest = hashlib.sha256(
        canonical_json_bytes(value, exclude_top_level=exclude_top_level)
    ).hexdigest()
    return f"sha256:{digest}"


def file_sha256(path: Path) -> str:
    """Return a prefixed streaming SHA-256 for one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    """Read one UTF-8 JSON object with a stable error boundary."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReproducibilityError(f"Could not read {label}: {path}") from error
    if not isinstance(value, dict):
        raise ReproducibilityError(f"{label} must be a JSON object: {path}")
    return value


def resolve_inside(root: Path, relative_path: str, label: str) -> Path:
    """Resolve a manifest path without permitting root escape."""
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ReproducibilityError(f"{label} must be relative to the staged root")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ReproducibilityError(f"{label} escapes the staged root")
    return candidate


def require_sha256(value: object, label: str) -> str:
    """Validate the roadmap's explicit prefixed SHA-256 representation."""
    if not isinstance(value, str):
        raise ReproducibilityError(f"{label} must be a prefixed SHA-256")
    prefix, separator, digest = value.partition(":")
    if separator != ":" or prefix != "sha256" or len(digest) != 64:
        raise ReproducibilityError(f"{label} must be a prefixed SHA-256")
    try:
        int(digest, 16)
    except ValueError as error:
        raise ReproducibilityError(f"{label} must be hexadecimal") from error
    return value


def require_aware_timestamp(value: object, label: str) -> datetime:
    """Parse a timezone-aware ISO-8601 release timestamp."""
    if not isinstance(value, str) or not value.strip():
        raise ReproducibilityError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReproducibilityError(f"{label} is not a valid timestamp") from error
    if parsed.tzinfo is None:
        raise ReproducibilityError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def git_metadata(repository_root: Path) -> dict[str, Any]:
    """Capture commit and dirty paths without mutating repository state."""

    def run(arguments: Sequence[str]) -> str:
        try:
            completed = subprocess.run(
                ["git", *arguments],
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except (OSError, subprocess.CalledProcessError) as error:
            raise ReproducibilityError("Git metadata is unavailable") from error
        return completed.stdout.rstrip("\r\n")

    commit_sha = run(("rev-parse", "HEAD"))
    status = run(("status", "--porcelain=v1", "--untracked-files=all"))
    dirty_paths = tuple(line[3:] for line in status.splitlines() if len(line) > 3)
    return {
        "commit_sha": commit_sha,
        "dirty": bool(status),
        "dirty_paths": dirty_paths,
    }


def build_experiment_record(
    *,
    repository_root: Path,
    experiment_id: str,
    command: Sequence[str],
    manifest_path: Path | None = None,
    output_path: Path | None = None,
    model: Mapping[str, Any] | None = None,
    evaluator_version: str,
    gate_result: str,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the minimum irreducible experiment identity from actual state."""
    now = (created_at or datetime.now(UTC)).astimezone(UTC)
    git = git_metadata(repository_root)
    lock_path = repository_root / "apps" / "api" / "uv.lock"
    git["uv_lock_sha256"] = file_sha256(lock_path)
    record: dict[str, Any] = {
        "schema_version": "dm.experiment.v1",
        "experiment_id": experiment_id,
        "created_at_utc": now.isoformat(),
        "git": git,
        "evaluator_version": evaluator_version,
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "command": list(command),
        "gate_result": gate_result,
    }
    if manifest_path is not None:
        record["manifest"] = {
            "path": manifest_path.resolve()
            .relative_to(repository_root.resolve())
            .as_posix()
            if manifest_path.resolve().is_relative_to(repository_root.resolve())
            else str(manifest_path.resolve()),
            "sha256": file_sha256(manifest_path.resolve()),
        }
    if output_path is not None:
        record["output_path"] = str(output_path.resolve())
        if output_path.is_file():
            record["output_sha256"] = file_sha256(output_path.resolve())
    if model is not None:
        record["model"] = dict(model)
    record["record_sha256"] = canonical_json_sha256(record)
    return record
