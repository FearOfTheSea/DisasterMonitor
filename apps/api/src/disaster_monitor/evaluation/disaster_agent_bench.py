"""Fail-closed DisasterAgentBench manifest validation and deterministic replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.evaluation.reproducibility import (
    ReproducibilityError,
    canonical_json_sha256,
    file_sha256,
    read_json_object,
    require_aware_timestamp,
    require_sha256,
    resolve_inside,
)

MANIFEST_VERSION = "dm.disasteragentbench.v1"
SNAPSHOT_MANIFEST_VERSION = "dm.source-snapshots.v1"
SELECTION_VERSION = "dm.disasteragentbench-selection.v1"


class DisasterAgentBenchError(ReproducibilityError):
    """A locked corpus prerequisite or integrity check failed."""


class ReplayMode(StrEnum):
    """Frozen operational and canonical replay orderings."""

    ORIGINAL_INGESTION_ORDER = "original-ingestion-order"
    CANONICAL_EFFECTIVE_TIME = "canonical-effective-time"


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """One immutable provider response in a benchmark episode."""

    snapshot_id: str
    source_id: str
    provider_record_id: str
    retrieved_at: datetime
    published_at: datetime | None
    observed_at: datetime | None
    request_fingerprint: str
    payload_relpath: str
    payload_sha256: str
    content_type: str
    parser_version: str
    rights_ref: str

    @property
    def effective_at(self) -> datetime:
        return self.observed_at or self.published_at or self.retrieved_at

    @property
    def logical_key(self) -> tuple[str, str, str]:
        return self.source_id, self.provider_record_id, self.request_fingerprint

    def identity(self) -> dict[str, str]:
        return {
            "snapshot_id": self.snapshot_id,
            "source_id": self.source_id,
            "provider_record_id": self.provider_record_id,
            "retrieved_at": self.retrieved_at.astimezone(UTC).isoformat(),
            "effective_at": self.effective_at.astimezone(UTC).isoformat(),
            "request_fingerprint": self.request_fingerprint,
            "payload_sha256": self.payload_sha256,
            "parser_version": self.parser_version,
        }


@dataclass(frozen=True, slots=True)
class Episode:
    """Runtime-safe benchmark episode with hidden label paths removed."""

    episode_id: str
    disaster: Disaster
    country_code: str
    start: datetime
    end: datetime
    snapshots: tuple[SourceSnapshot, ...]
    snapshot_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Deterministic evidence-set and effective-state replay result."""

    episode_id: str
    mode: ReplayMode
    ordered_snapshot_ids: tuple[str, ...]
    state_versions: tuple[str, ...]
    source_set_hash: str
    canonical_state_hash: str


@dataclass(frozen=True, slots=True)
class BenchIntegrityResult:
    """Machine-readable P0 integrity result; not an external validity claim."""

    manifest_id: str
    manifest_sha256: str
    episode_count: int
    snapshot_count: int
    deterministic_replay: bool
    hidden_labels_separated: bool
    integrity_passed: bool
    normative_release_passed: bool
    normative_release_blockers: tuple[str, ...]
    replay_results: tuple[ReplayResult, ...]


def validate_locked_manifest(
    manifest_path: Path, *, verify_payloads: bool = True
) -> tuple[dict[str, Any], tuple[Episode, ...]]:
    """Validate the umbrella manifest and return label-free runtime episodes."""
    path = manifest_path.resolve()
    root = path.parent
    manifest = read_json_object(path, "DisasterAgentBench release manifest")
    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise DisasterAgentBenchError("Unsupported DisasterAgentBench schema version")
    if manifest.get("role") != "release":
        raise DisasterAgentBenchError(
            "DisasterAgentBench manifest must have release role"
        )
    manifest_id = manifest.get("manifest_id")
    if not isinstance(manifest_id, str) or not manifest_id.strip():
        raise DisasterAgentBenchError("Release manifest requires a stable manifest ID")
    commit = manifest.get("created_from_commit")
    if not isinstance(commit, str) or len(commit) != 40:
        raise DisasterAgentBenchError("created_from_commit must be a 40-character SHA")
    try:
        int(commit, 16)
    except ValueError as error:
        raise DisasterAgentBenchError(
            "created_from_commit must be hexadecimal"
        ) from error
    require_aware_timestamp(manifest.get("created_at_utc"), "created_at_utc")
    declared_hash = require_sha256(manifest.get("manifest_sha256"), "manifest_sha256")
    actual_hash = canonical_json_sha256(
        manifest, exclude_top_level=frozenset({"manifest_sha256"})
    )
    if declared_hash != actual_hash:
        raise DisasterAgentBenchError("Release manifest canonical hash does not match")
    raw_episodes = manifest.get("episodes")
    if not isinstance(raw_episodes, list) or not raw_episodes:
        raise DisasterAgentBenchError("Release manifest contains no episodes")
    episodes: list[Episode] = []
    seen: set[str] = set()
    for raw in raw_episodes:
        if not isinstance(raw, dict):
            raise DisasterAgentBenchError("Every release episode must be an object")
        episode = _load_episode(root, raw, verify_payloads=verify_payloads)
        if episode.episode_id in seen:
            raise DisasterAgentBenchError("Release episode IDs must be unique")
        seen.add(episode.episode_id)
        episodes.append(episode)
    return manifest, tuple(sorted(episodes, key=lambda item: item.episode_id))


def lock_selection(staged_root: Path, selection_path: Path) -> dict[str, Any]:
    """Hash an owner-curated external selection without copying its data."""
    root = staged_root.resolve()
    selection = read_json_object(selection_path.resolve(), "benchmark selection")
    if selection.get("schema_version") != SELECTION_VERSION:
        raise DisasterAgentBenchError("Unsupported benchmark selection schema")
    episodes = selection.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise DisasterAgentBenchError("Benchmark selection contains no episodes")
    locked: list[dict[str, Any]] = []
    for raw in episodes:
        if not isinstance(raw, dict):
            raise DisasterAgentBenchError("Selection episodes must be objects")
        item = dict(raw)
        snapshot_path = resolve_inside(
            root, _required_text(item, "source_snapshot_manifest"), "snapshot manifest"
        )
        if not snapshot_path.is_file():
            raise DisasterAgentBenchError(
                f"Snapshot manifest is absent: {snapshot_path}"
            )
        item["source_snapshot_manifest_sha256"] = file_sha256(snapshot_path)
        hidden_path = resolve_inside(
            root, _required_text(item, "hidden_labels_ref"), "hidden labels"
        )
        if not hidden_path.is_file():
            raise DisasterAgentBenchError(f"Hidden labels are absent: {hidden_path}")
        item["hidden_labels_sha256"] = file_sha256(hidden_path)
        _load_episode(root, item, verify_payloads=True)
        locked.append(item)
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_VERSION,
        "manifest_id": _required_text(selection, "manifest_id"),
        "role": "release",
        "created_from_commit": _required_text(selection, "created_from_commit"),
        "created_at_utc": _required_text(selection, "created_at_utc"),
        "episodes": sorted(locked, key=lambda item: str(item["episode_id"])),
    }
    manifest["manifest_sha256"] = canonical_json_sha256(manifest)
    return manifest


def replay_episode(episode: Episode, mode: ReplayMode) -> ReplayResult:
    """Replay immutable snapshots and derive order-independent final state hashes."""
    if mode == ReplayMode.ORIGINAL_INGESTION_ORDER:
        ordered = sorted(
            episode.snapshots,
            key=lambda item: (item.retrieved_at, item.snapshot_id),
        )
    else:
        ordered = sorted(
            episode.snapshots,
            key=lambda item: (item.effective_at, item.retrieved_at, item.snapshot_id),
        )
    accumulated: list[SourceSnapshot] = []
    versions: list[str] = []
    for snapshot in ordered:
        accumulated.append(snapshot)
        versions.append(_canonical_source_set_hash(accumulated))
    source_set_hash = _canonical_source_set_hash(episode.snapshots)
    canonical_state_hash = _canonical_effective_state_hash(episode.snapshots)
    return ReplayResult(
        episode_id=episode.episode_id,
        mode=mode,
        ordered_snapshot_ids=tuple(item.snapshot_id for item in ordered),
        state_versions=tuple(versions),
        source_set_hash=source_set_hash,
        canonical_state_hash=canonical_state_hash,
    )


def evaluate_integrity(manifest_path: Path) -> BenchIntegrityResult:
    """Run the repository-owned DAB integrity/replay gate and fail closed on studies."""
    manifest, episodes = validate_locked_manifest(manifest_path)
    replay_results: list[ReplayResult] = []
    deterministic = True
    for episode in episodes:
        operational = replay_episode(episode, ReplayMode.ORIGINAL_INGESTION_ORDER)
        canonical = replay_episode(episode, ReplayMode.CANONICAL_EFFECTIVE_TIME)
        repeated = replay_episode(episode, ReplayMode.CANONICAL_EFFECTIVE_TIME)
        replay_results.extend((operational, canonical))
        deterministic = deterministic and (
            operational.source_set_hash == canonical.source_set_hash
            and operational.canonical_state_hash == canonical.canonical_state_hash
            and canonical == repeated
        )
    blockers = (
        "External EW outcomes have not been independently adjudicated by this gate.",
        "TR-B requires blinded SME rankings.",
        "DS-A/DS-B require blinded expert review and held outcomes.",
        "MM-A/MM-B/MM-C remain governed by their locked external evaluators.",
    )
    declared_hash = str(manifest["manifest_sha256"])
    return BenchIntegrityResult(
        manifest_id=str(manifest["manifest_id"]),
        manifest_sha256=declared_hash,
        episode_count=len(episodes),
        snapshot_count=sum(len(item.snapshots) for item in episodes),
        deterministic_replay=deterministic,
        hidden_labels_separated=all(
            "hidden_labels_ref" not in asdict(episode) for episode in episodes
        ),
        integrity_passed=deterministic,
        normative_release_passed=False,
        normative_release_blockers=blockers,
        replay_results=tuple(replay_results),
    )


def episode_from_manifest(manifest_path: Path, episode_id: str) -> Episode:
    """Load one runtime-safe episode by stable ID."""
    _, episodes = validate_locked_manifest(manifest_path)
    for episode in episodes:
        if episode.episode_id == episode_id:
            return episode
    raise DisasterAgentBenchError(f"Episode is not present in manifest: {episode_id}")


def replay_result_payload(result: ReplayResult) -> dict[str, Any]:
    """Serialize replay enums explicitly for command-line artifacts."""
    payload = asdict(result)
    payload["mode"] = result.mode.value
    return payload


def _load_episode(root: Path, raw: dict[str, Any], *, verify_payloads: bool) -> Episode:
    episode_id = _required_text(raw, "episode_id")
    try:
        disaster = Disaster(_required_text(raw, "disaster"))
    except ValueError as error:
        raise DisasterAgentBenchError(
            f"Episode {episode_id} has invalid disaster"
        ) from error
    country_code = _required_text(raw, "country_code")
    if len(country_code) != 3 or not country_code.isalpha():
        raise DisasterAgentBenchError("Episode country_code must be ISO alpha-3")
    time_window = raw.get("time_window")
    if not isinstance(time_window, dict):
        raise DisasterAgentBenchError("Episode requires a time_window object")
    start = require_aware_timestamp(time_window.get("start"), "time_window.start")
    end = require_aware_timestamp(time_window.get("end"), "time_window.end")
    if end <= start:
        raise DisasterAgentBenchError("Episode time window must have positive duration")
    snapshot_ref = _required_text(raw, "source_snapshot_manifest")
    snapshot_path = resolve_inside(root, snapshot_ref, "source snapshot manifest")
    if not snapshot_path.is_file():
        raise DisasterAgentBenchError(f"Snapshot manifest is absent: {snapshot_path}")
    expected_snapshot_hash = require_sha256(
        raw.get("source_snapshot_manifest_sha256"),
        "source_snapshot_manifest_sha256",
    )
    if file_sha256(snapshot_path) != expected_snapshot_hash:
        raise DisasterAgentBenchError("Source snapshot manifest checksum mismatch")
    hidden_ref = _required_text(raw, "hidden_labels_ref")
    hidden_path = resolve_inside(root, hidden_ref, "hidden labels")
    expected_hidden_hash = require_sha256(
        raw.get("hidden_labels_sha256"), "hidden_labels_sha256"
    )
    if verify_payloads:
        if (
            not hidden_path.is_file()
            or file_sha256(hidden_path) != expected_hidden_hash
        ):
            raise DisasterAgentBenchError("Hidden label file is absent or changed")
    snapshot_document = read_json_object(snapshot_path, "source snapshot manifest")
    if snapshot_document.get("schema_version") != SNAPSHOT_MANIFEST_VERSION:
        raise DisasterAgentBenchError("Unsupported source snapshot schema version")
    raw_snapshots = snapshot_document.get("snapshots")
    if not isinstance(raw_snapshots, list) or not raw_snapshots:
        raise DisasterAgentBenchError("Episode contains no source snapshots")
    snapshots: list[SourceSnapshot] = []
    seen: set[str] = set()
    for item in raw_snapshots:
        if not isinstance(item, dict):
            raise DisasterAgentBenchError("Source snapshots must be objects")
        snapshot = _parse_snapshot(root, snapshot_path.parent, item, verify_payloads)
        if snapshot.snapshot_id in seen:
            raise DisasterAgentBenchError(
                "Snapshot IDs must be unique within an episode"
            )
        seen.add(snapshot.snapshot_id)
        snapshots.append(snapshot)
    return Episode(
        episode_id=episode_id,
        disaster=disaster,
        country_code=country_code.upper(),
        start=start,
        end=end,
        snapshots=tuple(snapshots),
        snapshot_manifest_sha256=expected_snapshot_hash,
    )


def _parse_snapshot(
    root: Path,
    snapshot_root: Path,
    raw: dict[str, Any],
    verify_payloads: bool,
) -> SourceSnapshot:
    retrieved = require_aware_timestamp(raw.get("retrieved_at"), "retrieved_at")
    published = _optional_timestamp(raw.get("published_at"), "published_at")
    observed = _optional_timestamp(raw.get("observed_at"), "observed_at")
    payload_relpath = _required_text(raw, "payload_relpath")
    payload = resolve_inside(snapshot_root, payload_relpath, "snapshot payload")
    payload_hash = require_sha256(raw.get("payload_sha256"), "payload_sha256")
    rights_ref = _required_text(raw, "rights_ref")
    rights = resolve_inside(root, rights_ref, "rights record")
    if verify_payloads:
        if not payload.is_file() or file_sha256(payload) != payload_hash:
            raise DisasterAgentBenchError("Snapshot payload is absent or changed")
        if not rights.is_file():
            raise DisasterAgentBenchError("Snapshot rights record is absent")
    return SourceSnapshot(
        snapshot_id=_required_text(raw, "snapshot_id"),
        source_id=_required_text(raw, "source_id"),
        provider_record_id=_required_text(raw, "provider_record_id"),
        retrieved_at=retrieved,
        published_at=published,
        observed_at=observed,
        request_fingerprint=require_sha256(
            raw.get("request_fingerprint"), "request_fingerprint"
        ),
        payload_relpath=payload_relpath,
        payload_sha256=payload_hash,
        content_type=_required_text(raw, "content_type"),
        parser_version=_required_text(raw, "parser_version"),
        rights_ref=rights_ref,
    )


def _canonical_source_set_hash(snapshots: Any) -> str:
    identities = sorted(
        (item.identity() for item in snapshots),
        key=lambda item: (item["source_id"], item["snapshot_id"]),
    )
    return canonical_json_sha256({"source_snapshots": identities})


def _canonical_effective_state_hash(snapshots: Any) -> str:
    latest: dict[tuple[str, str, str], SourceSnapshot] = {}
    for snapshot in snapshots:
        current = latest.get(snapshot.logical_key)
        if current is None or (
            snapshot.effective_at,
            snapshot.retrieved_at,
            snapshot.snapshot_id,
        ) > (current.effective_at, current.retrieved_at, current.snapshot_id):
            latest[snapshot.logical_key] = snapshot
    identities = sorted(
        (item.identity() for item in latest.values()),
        key=lambda item: (item["source_id"], item["provider_record_id"]),
    )
    return canonical_json_sha256({"effective_state": identities})


def _required_text(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item.strip():
        raise DisasterAgentBenchError(f"Required field is missing: {field}")
    return item.strip()


def _optional_timestamp(value: object, label: str) -> datetime | None:
    return None if value is None else require_aware_timestamp(value, label)
