"""Fail-closed full multimodal release evaluation over locked external assets."""

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.ports.visual_analysis import VisualAnalyzer
from disaster_monitor.application.services.common_operational_picture import (
    CommonOperationalPictureBuilder,
)
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_state import (
    build_evidence_world_state,
)
from disaster_monitor.application.services.multimodal_asset_admission import (
    MultimodalAssetAdmissionService,
)
from disaster_monitor.application.services.multimodal_association import (
    MultimodalEventAssociator,
)
from disaster_monitor.application.services.multimodal_state import (
    build_multimodal_evidence_state,
)
from disaster_monitor.application.services.visual_analysis import VisualAnalysisService
from disaster_monitor.domain.disaster import (
    Country,
    DisasterEvent,
    GeographicArea,
    Hazard,
    PhysicalEventIdentity,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.domain.multimodal import (
    AnalyticalMapLayer,
    CaptureRole,
    DamageLevel,
    EventAssociationStatus,
    VisualAnalysisConfiguration,
    VisualObservationKind,
    VisualObservationStatus,
)
from disaster_monitor.evaluation.multimodal_metrics import (
    MapFeatureEvaluation,
    MapScore,
    MultimodalGateScore,
    VqaCase,
    VqaPrediction,
    score_associations,
    score_classification,
    score_map_features,
    score_vqa,
)

MANIFEST_VERSION = "dm-mm-locked-v1"
SPECIFICATION_VERSION = "dm-mm-release-v1"
REQUIRED_FAMILIES = {"xBD", "FloodNet", "DisasterInsight", "DM-held-out"}
REQUIRED_ASSOCIATION_STATUSES = {"associated", "ambiguous", "unmatched", "orphaned"}
DAMAGE_CLASSES = (
    "no_visible_damage",
    "minor_damage",
    "major_damage",
    "destroyed",
)


class MultimodalReleaseError(RuntimeError):
    """A prerequisite or integrity failure that must never be treated as a skip."""


@dataclass(frozen=True, slots=True)
class ReleaseEvaluation:
    manifest_version: str
    manifest_sha256: str
    specification_version: str
    specification_sha256: str
    evaluated_at: str
    model: dict[str, Any]
    sample_count: int
    model_call_count: int
    evaluation_runtime_seconds: float
    dataset_families: tuple[str, ...]
    metrics: dict[str, Any]
    capability_passed: bool
    safety_passed: bool
    passed: bool


async def evaluate_locked_release(
    *,
    staged_root: Path,
    manifest_path: Path,
    specification_path: Path,
    analyzer: VisualAnalyzer,
    evaluated_at: datetime | None = None,
) -> ReleaseEvaluation:
    """Evaluate actual predictions and application artifacts from one locked slice."""
    root = staged_root.resolve()
    manifest_file = manifest_path.resolve()
    specification_file = specification_path.resolve()
    manifest = _read_json(manifest_file, "locked benchmark manifest")
    specification = _read_json(specification_file, "benchmark specification")
    samples = validate_release_inputs(
        root=root,
        manifest=manifest,
        specification=specification,
        specification_path=specification_file,
    )

    readiness = await analyzer.check_readiness()
    if not readiness.runtime_available:
        raise MultimodalReleaseError(
            "the configured local visual runtime is unavailable"
        )
    if not readiness.model_available:
        raise MultimodalReleaseError(
            f"the configured real visual model is absent: {readiness.model_id}"
        )
    if readiness.prompt_version != manifest["prompt_version"]:
        raise MultimodalReleaseError(
            "model prompt version differs from the locked manifest"
        )
    if readiness.preprocessing_version != manifest["preprocessing_version"]:
        raise MultimodalReleaseError(
            "model preprocessing version differs from the locked manifest"
        )

    now = evaluated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise MultimodalReleaseError("evaluation time must be timezone-aware")
    admission = MultimodalAssetAdmissionService(clock=lambda: now)
    associator = MultimodalEventAssociator()
    visual = VisualAnalysisService(analyzer, clock=lambda: now)
    cop_builder = CommonOperationalPictureBuilder()

    expected_damage: list[str] = []
    predicted_damage: list[str] = []
    expected_vqa: list[VqaCase] = []
    predicted_vqa: list[VqaPrediction] = []
    expected_associations: list[str] = []
    predicted_associations: list[str] = []
    expected_geotemporal: list[tuple[bool | None, bool | None]] = []
    predicted_geotemporal: list[tuple[bool | None, bool | None]] = []
    map_features: list[MapFeatureEvaluation] = []
    configurations: set[VisualAnalysisConfiguration] = set()
    model_call_count = 0
    started_at = perf_counter()

    for sample in samples:
        physical_event = _physical_event(sample, now)
        asset = admission.admit(_admission_input(root, sample))
        association = associator.associate(asset, physical_event)
        expected_status = str(sample["expected_association"])
        expected_associations.append(expected_status)
        predicted_associations.append(association.status.value)
        expected_geotemporal.append(
            (
                _optional_bool(sample.get("expected_geography_match")),
                _optional_bool(sample.get("expected_time_match")),
            )
        )
        predicted_geotemporal.append(
            (association.geography_match, association.time_match)
        )

        task = sample["task"]
        if task == "association":
            continue
        observations = await visual.analyze(
            asset,
            association,
            question=sample.get("question")
            if task == "visual_question_answering"
            else None,
        )
        model_call_count += 1
        configurations.update(item.configuration for item in observations)
        damage = next(
            (
                item
                for item in observations
                if item.kind == VisualObservationKind.DAMAGE_ASSESSMENT
            ),
            None,
        )
        if task == "damage_classification":
            expected_damage.append(str(sample["expected_damage"]))
            predicted_damage.append(
                damage.damage_level.value
                if damage is not None and damage.damage_level is not None
                else DamageLevel.UNKNOWN.value
            )
        else:
            expected_vqa.append(
                VqaCase(
                    expected_answer=sample.get("expected_answer"),
                    answerable=bool(sample["answerable"]),
                    prohibited=bool(sample.get("prohibited", False)),
                )
            )
            answer_observation = next(
                (
                    item
                    for item in observations
                    if item.kind == VisualObservationKind.VISUAL_QUESTION_ANSWER
                ),
                None,
            )
            answer = answer_observation.answer if answer_observation else None
            leakage_terms = (
                str(sample["sample_id"]),
                str(sample["dataset_family"]),
            )
            predicted_vqa.append(
                VqaPrediction(
                    answer=answer,
                    abstained=(
                        answer_observation is None
                        or answer_observation.status
                        == VisualObservationStatus.ABSTAINED
                    ),
                    leakage_detected=bool(
                        answer
                        and any(
                            term.casefold() in answer.casefold()
                            for term in leakage_terms
                        )
                    ),
                )
            )

        if damage is not None:
            evidence_state = build_evidence_world_state(
                physical_event.event,
                (),
                evaluated_at=now,
                physical_event=physical_event,
            )
            multimodal_state = build_multimodal_evidence_state(
                evidence_state,
                (asset,),
                (association,),
                observations,
                evaluated_at=now,
            )
            cop = cop_builder.build(multimodal_state, created_at=now)
            if cop is not None:
                for layer in cop.layers:
                    layer_type = (
                        "analytical"
                        if isinstance(layer, AnalyticalMapLayer)
                        else "source"
                    )
                    map_features.append(
                        MapFeatureEvaluation(
                            layer_type=layer_type,
                            authority=f"{layer_type}_layer",
                            source_asset_ids=layer.source_asset_ids,
                            observation_ids=getattr(
                                layer, "visual_observation_ids", ()
                            ),
                            attribution=layer.attribution,
                            status=layer.status.value,
                            uncertainty=layer.uncertainty,
                            artifact_type="layer",
                        )
                    )
                    for feature in layer.features:
                        map_features.append(
                            MapFeatureEvaluation(
                                layer_type=layer_type,
                                authority=feature.authority.value,
                                source_asset_ids=feature.source_asset_ids,
                                observation_ids=getattr(
                                    feature, "visual_observation_ids", ()
                                ),
                                attribution=feature.attribution,
                                status=feature.status.value,
                                uncertainty=feature.uncertainty,
                            )
                        )

    damage_score = score_classification(
        expected_damage, predicted_damage, classes=DAMAGE_CLASSES
    )
    baseline_score = score_classification(
        expected_damage,
        ["no_visible_damage"] * len(expected_damage),
        classes=DAMAGE_CLASSES,
    )
    vqa_score = score_vqa(expected_vqa, predicted_vqa)
    association_score = score_associations(
        expected_associations,
        predicted_associations,
        expected_geotemporal,
        predicted_geotemporal,
    )
    map_score = (
        score_map_features(map_features)
        if map_features
        else MapScore(0.0, 0.0, 0.0, 0, 0)
    )
    gate = MultimodalGateScore(
        damage_score, baseline_score, vqa_score, association_score, map_score
    )
    if len(configurations) != 1:
        raise MultimodalReleaseError(
            "visual analysis configuration changed within the locked release run"
        )
    configuration = next(iter(configurations))
    model_metadata = asdict(readiness)
    model_metadata.update(
        {
            "analysis_version": configuration.analysis_version,
            "maximum_output_tokens": configuration.maximum_output_tokens,
            "temperature": configuration.temperature,
            "seed": configuration.seed,
        }
    )
    return ReleaseEvaluation(
        manifest_version=str(manifest["manifest_version"]),
        manifest_sha256=_sha256(manifest_file),
        specification_version=str(specification["specification_version"]),
        specification_sha256=_sha256(specification_file),
        evaluated_at=now.isoformat(),
        model=model_metadata,
        sample_count=len(samples),
        model_call_count=model_call_count,
        evaluation_runtime_seconds=perf_counter() - started_at,
        dataset_families=tuple(
            sorted({str(item["dataset_family"]) for item in samples})
        ),
        metrics={
            "damage": asdict(damage_score),
            "frozen_baseline": asdict(baseline_score),
            "vqa": asdict(vqa_score),
            "association": asdict(association_score),
            "map": asdict(map_score),
        },
        capability_passed=gate.capability_passed,
        safety_passed=gate.safety_passed,
        passed=gate.passed,
    )


def validate_release_inputs(
    *,
    root: Path,
    manifest: dict[str, Any],
    specification: dict[str, Any],
    specification_path: Path,
) -> list[dict[str, Any]]:
    """Validate lock integrity and normative coverage before model execution."""
    if not root.is_dir():
        raise MultimodalReleaseError(f"staged benchmark root is absent: {root}")
    if specification.get("specification_version") != SPECIFICATION_VERSION:
        raise MultimodalReleaseError("benchmark specification version is not supported")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise MultimodalReleaseError(
            "locked benchmark manifest version is not supported"
        )
    if manifest.get("specification_sha256") != _sha256(specification_path):
        raise MultimodalReleaseError(
            "benchmark specification checksum changed after locking"
        )
    if manifest.get("frozen_baseline") != "constant-no-visible-damage-v1":
        raise MultimodalReleaseError("the required frozen baseline is not locked")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or not samples:
        raise MultimodalReleaseError("locked benchmark manifest contains no samples")
    if any(not isinstance(item, dict) for item in samples):
        raise MultimodalReleaseError("locked benchmark samples must be objects")
    typed_samples: list[dict[str, Any]] = samples
    families = {str(item.get("dataset_family")) for item in typed_samples}
    if families != REQUIRED_FAMILIES:
        raise MultimodalReleaseError(
            "locked release does not cover every named benchmark family"
        )
    sample_ids = [str(item.get("sample_id", "")) for item in typed_samples]
    development_ids = {str(item) for item in manifest.get("development_sample_ids", [])}
    if not all(sample_ids) or len(sample_ids) != len(set(sample_ids)):
        raise MultimodalReleaseError("locked sample IDs must be non-empty and unique")
    if set(sample_ids) & development_ids:
        raise MultimodalReleaseError("held-out and development sample IDs overlap")

    damage_labels: set[str] = set()
    vqa_coverage: set[str] = set()
    association_coverage: set[str] = set()
    for sample in typed_samples:
        _validate_sample(root, sample)
        task = str(sample["task"])
        status = str(sample["expected_association"])
        association_coverage.add(status)
        if task == "damage_classification":
            damage_labels.add(str(sample["expected_damage"]))
            if status != EventAssociationStatus.ASSOCIATED:
                raise MultimodalReleaseError(
                    "damage labels may only be scored on associated assets"
                )
        elif task == "visual_question_answering":
            if status != EventAssociationStatus.ASSOCIATED:
                raise MultimodalReleaseError(
                    "VQA may only be scored on associated assets"
                )
            if sample.get("prohibited") is True:
                vqa_coverage.add("prohibited")
            elif sample.get("answerable") is True:
                vqa_coverage.add("answerable")
            else:
                vqa_coverage.add("unanswerable")
    if damage_labels != set(DAMAGE_CLASSES):
        raise MultimodalReleaseError(
            "damage slice must include every frozen damage class"
        )
    if vqa_coverage != {"answerable", "unanswerable", "prohibited"}:
        raise MultimodalReleaseError(
            "VQA slice must include answerable, unanswerable, and prohibited cases"
        )
    if association_coverage != REQUIRED_ASSOCIATION_STATUSES:
        raise MultimodalReleaseError(
            "association slice must include associated, ambiguous, unmatched, "
            "and orphaned cases"
        )
    return typed_samples


def _validate_sample(root: Path, sample: dict[str, Any]) -> None:
    required = {
        "sample_id",
        "dataset_family",
        "dataset_version",
        "split",
        "task",
        "relative_path",
        "sha256",
        "source_id",
        "attribution",
        "captured_at",
        "capture_role",
        "hazard",
        "country_code",
        "footprint",
        "event",
        "expected_association",
        "expected_geography_match",
        "expected_time_match",
        "license_or_dataset_identity",
    }
    missing = required - set(sample)
    if missing:
        raise MultimodalReleaseError(
            f"locked sample is missing fields: {sorted(missing)}"
        )
    if sample["split"] != "held_out":
        raise MultimodalReleaseError("every release sample must use the held_out split")
    if sample["task"] not in {
        "damage_classification",
        "visual_question_answering",
        "association",
    }:
        raise MultimodalReleaseError("locked sample has an unsupported task")
    if sample["expected_association"] not in REQUIRED_ASSOCIATION_STATUSES:
        raise MultimodalReleaseError("locked sample has an invalid association label")
    candidate = (root / Path(str(sample["relative_path"]))).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise MultimodalReleaseError(
            "locked sample file is absent or escapes staged root"
        )
    if sample["sha256"] != _sha256(candidate):
        raise MultimodalReleaseError(
            f"locked sample checksum mismatch: {sample['sample_id']}"
        )
    _aware_datetime(sample.get("captured_at"), allow_none=True)
    event = sample.get("event")
    if not isinstance(event, dict):
        raise MultimodalReleaseError("locked sample event must be an object")
    for field in ("event_id", "event_time", "longitude", "latitude"):
        if field not in event:
            raise MultimodalReleaseError(f"locked sample event is missing {field}")
    _aware_datetime(event["event_time"])
    try:
        Hazard(str(sample["hazard"]))
        CaptureRole(str(sample["capture_role"]))
    except ValueError as error:
        raise MultimodalReleaseError(
            "locked sample has invalid hazard or capture role"
        ) from error
    if (
        sample["task"] == "damage_classification"
        and sample.get("expected_damage") not in DAMAGE_CLASSES
    ):
        raise MultimodalReleaseError("damage sample has no valid frozen class")
    if sample["task"] == "visual_question_answering":
        if (
            not isinstance(sample.get("question"), str)
            or not sample["question"].strip()
        ):
            raise MultimodalReleaseError("VQA sample requires a non-empty question")
        if not isinstance(sample.get("answerable"), bool):
            raise MultimodalReleaseError("VQA sample requires answerable metadata")
        if sample["answerable"] and not isinstance(sample.get("expected_answer"), str):
            raise MultimodalReleaseError(
                "answerable VQA sample requires expected_answer"
            )


def _admission_input(root: Path, sample: dict[str, Any]) -> AssetAdmissionInput:
    footprint = sample.get("footprint")
    coordinates = None
    if footprint is not None:
        try:
            coordinates = tuple(
                tuple((float(point[0]), float(point[1])) for point in ring)
                for ring in footprint
            )
        except (TypeError, ValueError, IndexError) as error:
            raise MultimodalReleaseError(
                "locked footprint coordinates are invalid"
            ) from error
    return AssetAdmissionInput(
        content=(root / Path(str(sample["relative_path"]))).read_bytes(),
        attribution=str(sample["attribution"]),
        captured_at=_aware_datetime(sample.get("captured_at"), allow_none=True),
        footprint_coordinates=coordinates,
        declared_hazard=Hazard(str(sample["hazard"])),
        declared_country_code=str(sample["country_code"]),
        capture_role=CaptureRole(str(sample["capture_role"])),
        dataset_id=str(sample["source_id"]),
        license_name=str(sample["license_or_dataset_identity"]),
        processing_level="raw",
        event_id_hint=(
            str(sample["event_id_hint"]) if sample.get("event_id_hint") else None
        ),
    )


def _physical_event(sample: dict[str, Any], now: datetime) -> PhysicalEventIdentity:
    event_item = sample["event"]
    event_time = _aware_datetime(event_item["event_time"])
    assert event_time is not None
    country_code = str(event_item.get("country_code", sample["country_code"])).upper()
    country = Country(
        country_code,
        f"Evaluation country {country_code}",
        (),
        GeographicArea(-90, 90, -180, 180),
        "UTC",
    )
    source = SourceReference(
        source_id="multimodal-release-event-source",
        publisher="Locked multimodal release manifest",
        title="Frozen benchmark event metadata",
        canonical_url="https://evaluation.invalid/multimodal-release-event",
        published_at=event_time,
        updated_at=event_time,
        retrieved_at=now,
    )
    event = DisasterEvent(
        event_id=str(event_item["event_id"]),
        hazard=Hazard(str(event_item.get("hazard", sample["hazard"]))),
        location="Locked multimodal evaluation footprint",
        country=country,
        event_time=event_time,
        source=source,
        geometry=point_event_geometry(
            float(event_item["latitude"]), float(event_item["longitude"]), source
        ),
        provider_ids=tuple(str(item) for item in event_item.get("provider_ids", [])),
    )
    return (
        default_event_policy_registry()
        .for_hazard(event.hazard)
        .identify((event,))
        .physical_events[0]
    )


def _read_json(path: Path, label: str) -> dict[str, Any]:
    import json

    if not path.is_file():
        raise MultimodalReleaseError(f"{label} is absent: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MultimodalReleaseError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise MultimodalReleaseError(f"{label} must be a JSON object")
    return value


def _aware_datetime(value: object, *, allow_none: bool = False) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise MultimodalReleaseError("locked timestamps must be ISO-8601 strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MultimodalReleaseError("locked timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise MultimodalReleaseError("locked timestamps must include a timezone")
    return parsed


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise MultimodalReleaseError(
            "expected geotemporal values must be boolean or null"
        )
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise MultimodalReleaseError(f"cannot hash required file: {path}") from error
    return digest.hexdigest()
