import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from disaster_monitor.application.multimodal import AssetAdmissionInput
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.multimodal_asset_admission import (
    MultimodalAssetAdmissionService,
)
from disaster_monitor.application.services.multimodal_association import (
    MultimodalEventAssociator,
)
from disaster_monitor.domain.disaster import (
    Country,
    DisasterEvent,
    GeographicArea,
    Hazard,
    SourceReference,
)
from disaster_monitor.domain.multimodal import CaptureRole
from disaster_monitor.evaluation.multimodal_metrics import (
    AssociationScore,
    MapFeatureEvaluation,
    MultimodalGateScore,
    VqaCase,
    VqaPrediction,
    score_associations,
    score_classification,
    score_map_features,
    score_vqa,
)
from disaster_monitor.evaluation.multimodal_release import (
    MultimodalReleaseError,
    validate_release_inputs,
)

FIXTURES = Path(__file__).parent / "fixtures" / "multimodal"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
CLASSES = (
    "no_visible_damage",
    "minor_damage",
    "major_damage",
    "destroyed",
)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _datetime(value: str | None) -> datetime | None:
    return (
        None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )


def _event(fixture: dict):
    item = fixture["event"]
    event_time = _datetime(item["event_time"])
    assert event_time is not None
    country = Country(
        item["country_code"],
        "Fixture country",
        (),
        GeographicArea(-90, 90, -180, 180),
        "UTC",
    )
    source = SourceReference(
        "mm-fast-event-source",
        "MM fixture scientific source",
        "MM fixture event",
        "https://example.test/mm-event",
        event_time,
        event_time,
        event_time,
    )
    event = DisasterEvent(
        item["event_id"],
        Hazard(item["hazard"]),
        "Fixture location",
        country,
        event_time,
        source,
        latitude=item["latitude"],
        longitude=item["longitude"],
        provider_ids=tuple(item["provider_ids"]),
    )
    return (
        default_event_policy_registry()
        .for_hazard(event.hazard)
        .identify((event,))
        .physical_events[0]
    )


def _association_score() -> AssociationScore:
    fixture = _load("geotemporal_cases.v1.json")
    physical_event = _event(fixture)
    footprints = fixture["footprints"]
    admission = MultimodalAssetAdmissionService(
        clock=lambda: datetime(2026, 8, 5, 12, tzinfo=UTC)
    )
    associator = MultimodalEventAssociator()
    expected_statuses = []
    predicted_statuses = []
    expected_geotemporal = []
    predicted_geotemporal = []
    for case in fixture["cases"]:
        footprint_name = case["footprint"]
        footprint = None if footprint_name is None else footprints[footprint_name]
        asset = admission.admit(
            AssetAdmissionInput(
                content=PNG,
                attribution=f"Fast MM fixture {case['case_id']}",
                captured_at=_datetime(case["capture"]),
                footprint_coordinates=(
                    None
                    if footprint is None
                    else tuple(
                        tuple((float(lon), float(lat)) for lon, lat in ring)
                        for ring in footprint
                    )
                ),
                declared_hazard=Hazard(case["hazard"]),
                declared_country_code=case["country"],
                capture_role=CaptureRole(case["role"]),
                processing_level="raw",
                event_id_hint=case.get("event_id_hint"),
            )
        )
        result = associator.associate(asset, physical_event)
        expected_statuses.append(case["expected_status"])
        predicted_statuses.append(result.status.value)
        expected_geotemporal.append((case["expected_geography"], case["expected_time"]))
        predicted_geotemporal.append((result.geography_match, result.time_match))
    return score_associations(
        expected_statuses,
        predicted_statuses,
        expected_geotemporal,
        predicted_geotemporal,
    )


def _healthy_gate() -> MultimodalGateScore:
    expected_damage = list(CLASSES) * 3
    damage = score_classification(expected_damage, expected_damage, classes=CLASSES)
    baseline = score_classification(
        expected_damage,
        ["no_visible_damage"] * len(expected_damage),
        classes=CLASSES,
    )
    vqa = score_vqa(
        [
            VqaCase("yes", True),
            VqaCase("two flooded roads", True),
            VqaCase(None, False),
            VqaCase(None, False, prohibited=True),
        ],
        [
            VqaPrediction("Yes.", False),
            VqaPrediction("two flooded roads", False),
            VqaPrediction(None, True),
            VqaPrediction(None, True),
        ],
    )
    map_score = score_map_features(
        [
            MapFeatureEvaluation(
                "source",
                "source_layer",
                ("asset:official",),
                (),
                "Source layer attribution",
                "current",
                "Source status as published.",
                "layer",
            ),
            MapFeatureEvaluation(
                "source",
                "official_source",
                ("asset:official",),
                (),
                "Official source",
                "current",
                "Source status as published.",
            ),
            MapFeatureEvaluation(
                "analytical",
                "analytical_layer",
                ("asset:image",),
                ("visual:1",),
                "Analytical layer attribution",
                "current",
                "Analytical estimate only.",
                "layer",
            ),
            MapFeatureEvaluation(
                "analytical",
                "analytical_generated",
                ("asset:image",),
                ("visual:1",),
                "Model and asset attribution",
                "current",
                "Analytical estimate only.",
            ),
        ]
    )
    return MultimodalGateScore(damage, baseline, vqa, _association_score(), map_score)


def test_fast_multimodal_release_gate_passes_frozen_safety_cases() -> None:
    gate = _healthy_gate()

    assert gate.damage.macro_f1 == 1
    assert gate.damage.macro_f1 > gate.frozen_baseline.macro_f1
    assert gate.vqa.factual_accuracy == 1
    assert gate.vqa.abstention_rate == 1
    assert gate.association.association_accuracy == 1
    assert gate.association.geotemporal_accuracy == 1
    assert gate.map_score.provenance_completeness == 1
    assert gate.passed


def test_evaluator_rejects_majority_accuracy_hiding_poor_macro_f1() -> None:
    expected = (
        ["no_visible_damage"] * 90
        + [
            "minor_damage",
            "major_damage",
            "destroyed",
        ]
        * 3
        + ["minor_damage"]
    )
    predicted = ["no_visible_damage"] * len(expected)

    score = score_classification(expected, predicted, classes=CLASSES)

    assert score.accuracy == 0.9
    assert score.macro_f1 < 0.85
    assert all(
        score.per_class[label].f1 == 0
        for label in ("minor_damage", "major_damage", "destroyed")
    )


def test_evaluator_rejects_unsupported_casualty_inference() -> None:
    score = score_vqa(
        [VqaCase(None, False, prohibited=True)],
        [VqaPrediction("12 people were killed", False)],
    )

    assert score.safety_violations == 1


@pytest.mark.parametrize(
    "feature",
    (
        MapFeatureEvaluation(
            "analytical",
            "analytical_generated",
            (),
            ("visual:1",),
            "Attribution",
            "current",
            "Uncertain",
        ),
        MapFeatureEvaluation(
            "analytical",
            "official_source",
            ("asset:1",),
            ("visual:1",),
            "Attribution",
            "current",
            "Uncertain",
        ),
        MapFeatureEvaluation(
            "analytical",
            "analytical_generated",
            ("asset:1",),
            ("visual:1",),
            "Attribution",
            "",
            "",
        ),
        MapFeatureEvaluation(
            "analytical",
            "analytical_layer",
            ("asset:1",),
            ("visual:1",),
            "Layer attribution",
            "",
            "",
            "layer",
        ),
    ),
)
def test_evaluator_rejects_lost_provenance_authority_or_hidden_status(feature) -> None:
    score = score_map_features([feature])

    assert (
        score.provenance_completeness < 1
        or score.authority_violations
        or score.visible_status_uncertainty < 1
    )


@pytest.mark.parametrize(
    ("expected", "predicted"),
    (
        ("orphaned", "associated"),
        ("unmatched", "associated"),
        ("ambiguous", "associated"),
    ),
)
def test_evaluator_rejects_missing_metadata_wrong_event_and_mismatch(
    expected, predicted
) -> None:
    score = score_associations(
        [expected],
        [predicted],
        [(False, False)],
        [(True, True)],
    )

    assert score.association_accuracy == 0
    assert score.geotemporal_accuracy == 0
    assert score.critical_wrong_event_count == 1


def test_evaluator_rejects_detected_prediction_leakage() -> None:
    score = score_vqa(
        [VqaCase("yes", True)],
        [VqaPrediction("yes", False, leakage_detected=True)],
    )

    assert score.factual_accuracy == 1
    assert score.leakage_violations == 1


def test_release_spec_is_explicitly_blocked_not_silently_skipped() -> None:
    specification = _load("benchmark_spec.v1.json")

    assert specification["status"] == "awaiting_licensed_external_assets"
    assert {item["family"] for item in specification["dataset_families"]} == {
        "xBD",
        "FloodNet",
        "DisasterInsight",
        "DM-held-out",
    }
    assert all(
        item["sample_selection_status"].startswith("blocked_")
        for item in specification["dataset_families"]
    )
    assert "sha256" in specification["required_locked_manifest_fields"]


def test_production_logic_contains_no_frozen_benchmark_sample_ids() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "disaster_monitor"
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in source_root.rglob("*.py")
        if "evaluation" not in path.parts
    ).casefold()

    assert "guatemala-volcano_00000023" not in production
    assert "dataset_family" not in production
    assert "sample_id" not in production


def test_full_release_gate_fails_closed_when_locked_assets_are_absent(
    tmp_path: Path,
) -> None:
    specification_path = FIXTURES / "benchmark_spec.v1.json"
    specification = _load("benchmark_spec.v1.json")
    manifest = {
        "manifest_version": "dm-mm-locked-v1",
        "specification_sha256": hashlib.sha256(
            specification_path.read_bytes()
        ).hexdigest(),
        "frozen_baseline": "constant-no-visible-damage-v1",
        "development_sample_ids": [],
        "samples": [],
    }

    with pytest.raises(MultimodalReleaseError, match="no samples"):
        validate_release_inputs(
            root=tmp_path,
            manifest=manifest,
            specification=specification,
            specification_path=specification_path,
        )
