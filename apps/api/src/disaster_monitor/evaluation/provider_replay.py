"""Offline, deterministic replay for the locked provider reference corpus."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx

from disaster_monitor.application.disaster import WorldwideDisasterQuery
from disaster_monitor.application.evidence.event_policies import (
    default_event_policy_registry,
)
from disaster_monitor.application.ports.disaster_information import (
    WorldwideDisasterProvider,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    GeographicArea,
)
from disaster_monitor.evaluation.reproducibility import (
    ReproducibilityError,
    file_sha256,
    read_json_object,
    require_aware_timestamp,
    require_sha256,
    resolve_inside,
)
from disaster_monitor.infrastructure.disaster.gdacs_adapter import (
    GdacsEarthquakeAdapter,
    GdacsFloodAdapter,
    GdacsTropicalCycloneAdapter,
    GdacsVolcanicEruptionAdapter,
)
from disaster_monitor.infrastructure.disaster.nasa_coolr_adapter import (
    NasaCoolrLandslideAdapter,
)
from disaster_monitor.infrastructure.disaster.nasa_eonet_adapter import (
    NasaEonetWildfireAdapter,
)

REQUIRED_HAZARDS = frozenset(
    {
        "earthquake",
        "flood",
        "wildfire",
        "landslide",
        "tropical_cyclone",
        "volcanic_eruption",
    }
)


@dataclass(frozen=True, slots=True)
class ReplayObservation:
    observation_id: str
    identity_key: str
    published_at: datetime
    retrieved_at: datetime
    expected_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderReplayCase:
    case_id: str
    hazard: str
    source_url: str
    payload_path: str
    payload_sha256: str
    expected_observation_ids: tuple[str, ...]
    expected_event_identity: str
    time_from: datetime
    time_to: datetime
    coverage_gaps: tuple[str, ...]
    independent_verification_urls: tuple[str, ...]
    adapter_id: str
    adapter_payload_path: str
    adapter_payload_sha256: str
    adapter_country_code: str
    adapter_now: datetime
    expected_adapter_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HazardReplayMetrics:
    hazard: str
    case_count: int
    expected_observations: int
    recalled_observations: int
    recall: float
    false_merge_count: int
    false_merge_rate: float
    false_split_count: int
    false_split_rate: float
    mean_latency_seconds: float | None


@dataclass(frozen=True, slots=True)
class ProviderReplayReport:
    corpus_version: str
    thresholds: dict[str, float]
    metrics: tuple[HazardReplayMetrics, ...]
    deterministic: bool
    promotion_eligible: bool
    scope_note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus_version": self.corpus_version,
            "thresholds": dict(self.thresholds),
            "metrics": [
                {
                    "hazard": item.hazard,
                    "case_count": item.case_count,
                    "expected_observations": item.expected_observations,
                    "recalled_observations": item.recalled_observations,
                    "recall": item.recall,
                    "false_merge_count": item.false_merge_count,
                    "false_merge_rate": item.false_merge_rate,
                    "false_split_count": item.false_split_count,
                    "false_split_rate": item.false_split_rate,
                    "mean_latency_seconds": item.mean_latency_seconds,
                }
                for item in self.metrics
            ],
            "deterministic": self.deterministic,
            "promotion_eligible": self.promotion_eligible,
            "scope_note": self.scope_note,
        }


def load_provider_corpus(
    path: Path,
) -> tuple[dict[str, Any], tuple[ProviderReplayCase, ...]]:
    """Load and validate a corpus manifest without contacting its source URLs."""
    document = read_json_object(path.resolve(), "provider corpus")
    if document.get("schema_version") != "provider-reference-corpus.v1":
        raise ReproducibilityError("Unsupported provider corpus schema version.")
    thresholds = document.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds.get("defined"):
        raise ReproducibilityError("Provider corpus thresholds must be defined.")
    cases_value = document.get("cases")
    if not isinstance(cases_value, list) or not cases_value:
        raise ReproducibilityError("Provider corpus must contain cases.")
    retrieval_date = require_aware_timestamp(
        f"{document.get('retrieval_date')}T00:00:00Z", "retrieval_date"
    )
    cases: list[ProviderReplayCase] = []
    seen: set[str] = set()
    for raw in cases_value:
        if not isinstance(raw, dict):
            raise ReproducibilityError("Provider corpus cases must be objects.")
        case_id = _required_text(raw, "case_id")
        if case_id in seen:
            raise ReproducibilityError(f"Duplicate provider corpus case: {case_id}")
        seen.add(case_id)
        expected = raw.get("expected_observations")
        if not isinstance(expected, list) or not expected:
            raise ReproducibilityError(f"Case {case_id} has no expected observations.")
        if not all(isinstance(item, dict) for item in expected):
            raise ReproducibilityError(
                f"Case {case_id} expected observations must be objects."
            )
        expected_ids = tuple(
            _required_text(item, "observation_id") for item in expected
        )
        if len(set(expected_ids)) != len(expected_ids):
            raise ReproducibilityError(f"Case {case_id} has duplicate expected IDs.")
        time_bounds = raw.get("time_bounds_utc")
        if not isinstance(time_bounds, dict):
            raise ReproducibilityError(f"Case {case_id} has no UTC time bounds.")
        time_from = require_aware_timestamp(time_bounds.get("from"), f"{case_id}.from")
        time_to = require_aware_timestamp(time_bounds.get("to"), f"{case_id}.to")
        if time_to < time_from:
            raise ReproducibilityError(f"Case {case_id} has reversed time bounds.")
        if time_to > retrieval_date:
            raise ReproducibilityError(
                f"Case {case_id} has a future time bound relative to retrieval date."
            )
        coverage_gaps = raw.get("coverage_gaps", [])
        if not isinstance(coverage_gaps, list) or not all(
            isinstance(item, str) and item.strip() for item in coverage_gaps
        ):
            raise ReproducibilityError(f"Case {case_id} has invalid coverage gaps.")
        verification_urls = raw.get("independent_verification_urls")
        if not isinstance(verification_urls, list) or len(verification_urls) < 2:
            raise ReproducibilityError(
                f"Case {case_id} requires two independent verification URLs."
            )
        parsed_verification_urls = tuple(
            _required_https_value(item, f"{case_id}.independent_verification_urls")
            for item in verification_urls
        )
        if len(set(parsed_verification_urls)) != len(parsed_verification_urls):
            raise ReproducibilityError(
                f"Case {case_id} has duplicate verification URLs."
            )
        adapter_replay = raw.get("adapter_replay")
        if not isinstance(adapter_replay, dict):
            raise ReproducibilityError(
                f"Case {case_id} has no adapter replay contract."
            )
        expected_adapter_ids = adapter_replay.get("expected_event_ids")
        if not isinstance(expected_adapter_ids, list) or not expected_adapter_ids:
            raise ReproducibilityError(
                f"Case {case_id} has no expected adapter event IDs."
            )
        cases.append(
            ProviderReplayCase(
                case_id=case_id,
                hazard=_required_text(raw, "hazard"),
                source_url=_required_https(raw, "source_url"),
                payload_path=_required_text(raw, "payload_path"),
                payload_sha256=require_sha256(
                    raw.get("payload_sha256"), f"{case_id}.payload_sha256"
                ),
                expected_observation_ids=expected_ids,
                expected_event_identity=_required_text(raw, "expected_event_identity"),
                time_from=time_from,
                time_to=time_to,
                coverage_gaps=tuple(coverage_gaps),
                independent_verification_urls=parsed_verification_urls,
                adapter_id=_required_text(adapter_replay, "adapter"),
                adapter_payload_path=_required_text(adapter_replay, "payload_path"),
                adapter_payload_sha256=require_sha256(
                    adapter_replay.get("payload_sha256"),
                    f"{case_id}.adapter_replay.payload_sha256",
                ),
                adapter_country_code=_required_text(adapter_replay, "country_code"),
                adapter_now=require_aware_timestamp(
                    adapter_replay.get("now"), f"{case_id}.adapter_replay.now"
                ),
                expected_adapter_event_ids=tuple(
                    _required_text_value(item, f"{case_id}.expected_event_ids")
                    for item in expected_adapter_ids
                ),
            )
        )
    hazards = {case.hazard for case in cases}
    missing = sorted(REQUIRED_HAZARDS - hazards)
    if missing:
        raise ReproducibilityError(
            "Provider corpus is missing hazards: " + ", ".join(missing)
        )
    return document, tuple(cases)


def replay_provider_corpus(path: Path) -> ProviderReplayReport:
    """Replay real provider adapters and identity policy against locked payloads."""
    return asyncio.run(_replay_provider_corpus(path))


async def _replay_provider_corpus(path: Path) -> ProviderReplayReport:
    document, cases = load_provider_corpus(path)
    root = path.resolve().parent
    observations_by_hazard: dict[str, list[ReplayObservation]] = defaultdict(list)
    expected_by_hazard: dict[str, int] = defaultdict(int)
    case_counts: dict[str, int] = defaultdict(int)
    merge_counts: dict[str, int] = defaultdict(int)
    split_counts: dict[str, int] = defaultdict(int)
    for case in cases:
        payload_path = resolve_inside(
            root, case.payload_path, f"{case.case_id}.payload_path"
        )
        if not payload_path.is_file():
            raise ReproducibilityError(
                f"Provider payload snapshot is missing: {payload_path}"
            )
        if file_sha256(payload_path) != case.payload_sha256:
            raise ReproducibilityError(
                f"Provider payload checksum mismatch: {case.case_id}"
            )
        payload = read_json_object(payload_path, f"{case.case_id} provider payload")
        snapshot = payload.get("snapshots", {}).get(case.case_id)
        if not isinstance(snapshot, dict):
            raise ReproducibilityError(
                f"Provider payload has no snapshot for {case.case_id}"
            )
        if snapshot.get("source_url") != case.source_url:
            raise ReproducibilityError(
                f"Provider payload source mismatch: {case.case_id}"
            )
        physical_event_count = await _replay_adapter(root.parent, case)
        observations = _observations(snapshot, case)
        expected_count = len(case.expected_observation_ids)
        expected_by_hazard[case.hazard] += expected_count
        case_counts[case.hazard] += 1
        observations_by_hazard[case.hazard].extend(observations)
        adapter_expected_count = len(case.expected_adapter_event_ids)
        merge_counts[case.hazard] += max(
            0, adapter_expected_count - physical_event_count
        )
        split_counts[case.hazard] += max(
            0, physical_event_count - adapter_expected_count
        )

    thresholds = _thresholds(document["thresholds"])
    metrics = tuple(
        _metrics(
            hazard,
            tuple(observations_by_hazard[hazard]),
            expected_by_hazard[hazard],
            case_counts[hazard],
            merge_counts[hazard],
            split_counts[hazard],
        )
        for hazard in sorted(REQUIRED_HAZARDS)
    )
    eligible = all(
        item.recall >= thresholds["recall_min"]
        and item.false_merge_rate <= thresholds["false_merge_rate_max"]
        and item.false_split_rate <= thresholds["false_split_rate_max"]
        and (
            item.mean_latency_seconds is None
            or item.mean_latency_seconds <= thresholds["latency_seconds_max"]
        )
        for item in metrics
    )
    return ProviderReplayReport(
        corpus_version=str(document["version"]),
        thresholds=thresholds,
        metrics=metrics,
        deterministic=True,
        promotion_eligible=eligible,
        scope_note=(
            "Metrics execute production adapters and event-identity policy against "
            "locked provider payloads. They remain corpus-scoped and do not support "
            "a global coverage claim."
        ),
    )


async def _replay_adapter(root: Path, case: ProviderReplayCase) -> int:
    payload_path = resolve_inside(
        root, case.adapter_payload_path, f"{case.case_id}.adapter_replay.payload_path"
    )
    if file_sha256(payload_path) != case.adapter_payload_sha256:
        raise ReproducibilityError(
            f"Provider adapter payload checksum mismatch: {case.case_id}"
        )
    payload = read_json_object(payload_path, f"{case.case_id} adapter payload")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload, separators=(",", ":")).encode(),
            request=request,
        )

    disaster = Disaster(case.hazard)
    adapter_type = _ADAPTERS.get(case.adapter_id)
    if adapter_type is None:
        raise ReproducibilityError(
            f"Provider replay adapter is unsupported: {case.adapter_id}"
        )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = cast(WorldwideDisasterProvider, adapter_type(client=client))
    try:
        query = WorldwideDisasterQuery(disaster=disaster, time_window_days=90, limit=50)
        batch = await adapter.find_worldwide_events(query, now=case.adapter_now)
    finally:
        await client.aclose()
    expected = set(case.expected_adapter_event_ids)
    observed = {event.event_id for event in batch.records}
    if observed != expected:
        raise ReproducibilityError(
            f"Provider adapter replay changed for {case.case_id}: "
            f"expected {sorted(expected)}, observed {sorted(observed)}"
        )
    replay_country = Country(
        alpha3_code=case.adapter_country_code,
        canonical_name=f"Replay country {case.adapter_country_code}",
        aliases=(),
        geographic_area=GeographicArea(-90, 90, -180, 180),
    )
    matched = tuple(
        DisasterEvent(
            event_id=event.event_id,
            disaster=event.disaster,
            location=event.location,
            country=replay_country,
            event_time=event.event_time,
            source=event.source,
            geometry=event.geometry,
            measurements=event.measurements,
            provider_ids=event.provider_ids,
            lineage_ids=event.lineage_ids,
            geography_status=EventGeographyStatus.WORLDWIDE,
            observation_kind=event.observation_kind,
            activity_status=event.activity_status,
        )
        for event in batch.records
        if event.event_id in expected
    )
    policy = default_event_policy_registry().for_disaster(disaster)
    return sum(len(policy.identify((event,)).physical_events) for event in matched)


def _observations(
    snapshot: dict[str, Any], case: ProviderReplayCase
) -> tuple[ReplayObservation, ...]:
    raw_observations = snapshot.get("observations")
    if not isinstance(raw_observations, list):
        raise ReproducibilityError(
            f"Provider payload observations are invalid: {case.case_id}"
        )
    values: list[ReplayObservation] = []
    for raw in raw_observations:
        if not isinstance(raw, dict):
            raise ReproducibilityError(
                f"Provider payload record is invalid: {case.case_id}"
            )
        published_at = require_aware_timestamp(raw.get("published_at"), "published_at")
        retrieved_at = require_aware_timestamp(raw.get("retrieved_at"), "retrieved_at")
        if retrieved_at < published_at:
            raise ReproducibilityError(
                f"Provider payload latency is negative: {case.case_id}"
            )
        expected_ids = raw.get("expected_ids", [])
        if not isinstance(expected_ids, list) or not all(
            isinstance(item, str) and item.strip() for item in expected_ids
        ):
            raise ReproducibilityError(
                f"Provider payload expected IDs are invalid: {case.case_id}"
            )
        observation_id = _required_text(raw, "observation_id")
        if observation_id not in case.expected_observation_ids:
            raise ReproducibilityError(
                f"Provider payload contains an unexpected observation: {case.case_id}"
            )
        if set(expected_ids) - set(case.expected_observation_ids):
            raise ReproducibilityError(
                f"Provider payload references an unexpected expected ID: {case.case_id}"
            )
        if raw.get("identity_key") != case.expected_event_identity:
            raise ReproducibilityError(
                f"Provider payload identity mismatch: {case.case_id}"
            )
        if not case.time_from <= published_at <= case.time_to:
            raise ReproducibilityError(
                f"Provider payload observation is outside case bounds: {case.case_id}"
            )
        values.append(
            ReplayObservation(
                observation_id=observation_id,
                identity_key=_required_text(raw, "identity_key"),
                published_at=published_at,
                retrieved_at=retrieved_at,
                expected_ids=tuple(expected_ids),
            )
        )
    return tuple(values)


def _metrics(
    hazard: str,
    observations: tuple[ReplayObservation, ...],
    expected_count: int,
    case_count: int,
    merge_count: int,
    split_count: int,
) -> HazardReplayMetrics:
    expected_ids = {
        expected_id
        for observation in observations
        for expected_id in observation.expected_ids
    }
    recalled = len(expected_ids)
    latencies = [
        (item.retrieved_at - item.published_at).total_seconds() for item in observations
    ]
    denominator = max(expected_count, 1)
    return HazardReplayMetrics(
        hazard=hazard,
        case_count=case_count,
        expected_observations=expected_count,
        recalled_observations=min(recalled, expected_count),
        recall=min(recalled, expected_count) / denominator,
        false_merge_count=merge_count,
        false_merge_rate=merge_count / denominator,
        false_split_count=split_count,
        false_split_rate=split_count / denominator,
        mean_latency_seconds=(sum(latencies) / len(latencies) if latencies else None),
    )


_ADAPTERS = {
    "gdacs-earthquake": GdacsEarthquakeAdapter,
    "gdacs-flood": GdacsFloodAdapter,
    "nasa-eonet-wildfire": NasaEonetWildfireAdapter,
    "nasa-coolr-landslide": NasaCoolrLandslideAdapter,
    "gdacs-tropical-cyclone": GdacsTropicalCycloneAdapter,
    "gdacs-volcanic-eruption": GdacsVolcanicEruptionAdapter,
}


def _thresholds(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ReproducibilityError("Provider corpus thresholds are invalid.")
    names = (
        "recall_min",
        "false_merge_rate_max",
        "false_split_rate_max",
        "latency_seconds_max",
    )
    result: dict[str, float] = {}
    for name in names:
        item = value.get(name)
        if not isinstance(item, (int, float)) or item < 0:
            raise ReproducibilityError(f"Provider corpus threshold is invalid: {name}")
        result[name] = float(item)
    return result


def _required_text(value: dict[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise ReproducibilityError(f"Provider corpus field {name} is required.")
    return item.strip()


def _required_https(value: dict[str, Any], name: str) -> str:
    item = _required_text(value, name)
    if not item.startswith("https://"):
        raise ReproducibilityError(f"Provider corpus field {name} must be HTTPS.")
    return item


def _required_https_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise ReproducibilityError(f"Provider corpus field {name} must be HTTPS.")
    return value


def _required_text_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReproducibilityError(f"Provider corpus field {name} is required.")
    return value.strip()


__all__ = [
    "HazardReplayMetrics",
    "ProviderReplayCase",
    "ProviderReplayReport",
    "REQUIRED_HAZARDS",
    "load_provider_corpus",
    "replay_provider_corpus",
]
