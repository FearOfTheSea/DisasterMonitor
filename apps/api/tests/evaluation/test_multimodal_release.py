import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from disaster_monitor.application.multimodal import (
    VisualAnalysisRequest,
    VisualModelPrediction,
    VisualModelReadiness,
)
from disaster_monitor.domain.multimodal import (
    DamageLevel,
    VisualAnalysisConfiguration,
)
from disaster_monitor.evaluation.benchmark_preparation import lock_manifest
from disaster_monitor.evaluation.multimodal_release import evaluate_locked_release

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000"
    "b51c0c020000000b4944415478da6364f80f00010501012718e3660000"
    "000049454e44ae426082"
)
INSIDE = [
    [
        [136.8, 34.8],
        [137.2, 34.8],
        [137.2, 35.2],
        [136.8, 35.2],
        [136.8, 34.8],
    ]
]
NEAR = [
    [
        [137.05, 34.8],
        [137.2, 34.8],
        [137.2, 35.2],
        [137.05, 35.2],
        [137.05, 34.8],
    ]
]


class LockedSliceFakeAnalyzer:
    def __init__(self, damage_by_hash: dict[str, DamageLevel], *, majority=False):
        self.damage_by_hash = damage_by_hash
        self.majority = majority
        self.requests: list[VisualAnalysisRequest] = []

    async def check_readiness(self) -> VisualModelReadiness:
        return VisualModelReadiness(
            True,
            True,
            "locked-slice-fake-vlm",
            "sha256:locked-slice-fake",
            "fake-adapter-v1",
            "dm-visual-analysis-v1",
            "original-png-jpeg-bytes-v1",
        )

    async def analyze(self, request: VisualAnalysisRequest) -> VisualModelPrediction:
        self.requests.append(request)
        damage = (
            DamageLevel.NO_VISIBLE_DAMAGE
            if self.majority
            else self.damage_by_hash.get(
                request.asset.content_sha256, DamageLevel.NO_VISIBLE_DAMAGE
            )
        )
        answer = "yes" if request.question == "Is a road visibly flooded?" else None
        return VisualModelPrediction(
            damage_level=damage,
            damage_confidence=0.88,
            damage_cues=("bounded test cue",),
            answer=answer,
            answerable=answer is not None,
            answer_confidence=0.91 if answer else None,
            answer_cues=("visible water",) if answer else (),
            configuration=VisualAnalysisConfiguration(
                model_id="locked-slice-fake-vlm",
                model_digest="sha256:locked-slice-fake",
                adapter_version="fake-adapter-v1",
                analysis_version="bounded-damage-vqa-v1",
                prompt_version="dm-visual-analysis-v1",
                preprocessing_version="original-png-jpeg-bytes-v1",
                maximum_output_tokens=384,
                temperature=0,
                seed=7,
            ),
        )


def _stage_locked_slice(tmp_path: Path) -> tuple[Path, Path, dict[str, DamageLevel]]:
    specification = (
        Path(__file__).parent / "fixtures" / "multimodal" / "benchmark_spec.v1.json"
    )
    assets = tmp_path / "assets"
    assets.mkdir()
    samples: list[dict] = []
    damage_by_hash: dict[str, DamageLevel] = {}

    def add_sample(
        sample_id: str,
        family: str,
        task: str,
        index: int,
        *,
        expected_damage: str | None = None,
        question: str | None = None,
        expected_answer: str | None = None,
        answerable: bool | None = None,
        prohibited: bool = False,
        expected_association: str = "associated",
        expected_geography: bool | None = True,
        expected_time: bool | None = True,
        footprint=INSIDE,
        captured_at: str | None = "2026-08-05T14:00:00Z",
        country: str = "JPN",
        event_country: str = "JPN",
    ) -> None:
        content = PNG[:-1] + bytes([index])
        relative = Path("assets") / f"case-{index}.png"
        (tmp_path / relative).write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        item = {
            "sample_id": sample_id,
            "dataset_family": family,
            "dataset_version": "frozen-test-v1",
            "split": "held_out",
            "task": task,
            "relative_path": relative.as_posix(),
            "sha256": checksum,
            "source_id": f"locked-source-{family.casefold()}",
            "attribution": f"Locked {family} evaluator fixture",
            "captured_at": captured_at,
            "capture_role": "post_event",
            "hazard": "earthquake",
            "country_code": country,
            "footprint": footprint,
            "event": {
                "event_id": "fixture:event-1",
                "event_time": "2026-08-05T12:00:00Z",
                "longitude": 137.0,
                "latitude": 35.0,
                "country_code": event_country,
                "hazard": "earthquake",
            },
            "expected_association": expected_association,
            "expected_geography_match": expected_geography,
            "expected_time_match": expected_time,
            "license_or_dataset_identity": "test-fixture-only",
        }
        if expected_damage is not None:
            item["expected_damage"] = expected_damage
            damage_by_hash[checksum] = DamageLevel(expected_damage)
        if question is not None:
            item.update(
                question=question,
                expected_answer=expected_answer,
                answerable=answerable,
                prohibited=prohibited,
            )
        samples.append(item)

    for index, (family, label) in enumerate(
        (
            ("xBD", "no_visible_damage"),
            ("xBD", "minor_damage"),
            ("DisasterInsight", "major_damage"),
            ("FloodNet", "destroyed"),
        ),
        start=1,
    ):
        add_sample(
            f"damage-{index}",
            family,
            "damage_classification",
            index,
            expected_damage=label,
        )
    add_sample(
        "vqa-answerable",
        "FloodNet",
        "visual_question_answering",
        5,
        question="Is a road visibly flooded?",
        expected_answer="yes",
        answerable=True,
    )
    add_sample(
        "vqa-unanswerable",
        "DM-held-out",
        "visual_question_answering",
        6,
        question="What is inside the obscured building?",
        answerable=False,
    )
    add_sample(
        "vqa-prohibited",
        "DM-held-out",
        "visual_question_answering",
        7,
        question="How many people were killed?",
        answerable=False,
        prohibited=True,
    )
    add_sample(
        "association-ambiguous",
        "DM-held-out",
        "association",
        8,
        expected_association="ambiguous",
        expected_geography=False,
        footprint=NEAR,
    )
    add_sample(
        "association-unmatched",
        "DM-held-out",
        "association",
        9,
        expected_association="unmatched",
        country="VNM",
    )
    add_sample(
        "association-orphaned",
        "DM-held-out",
        "association",
        10,
        expected_association="orphaned",
        expected_geography=None,
        expected_time=None,
        footprint=None,
        captured_at=None,
    )
    manifest = {
        "manifest_version": "dm-mm-locked-v1",
        "specification_sha256": hashlib.sha256(specification.read_bytes()).hexdigest(),
        "prompt_version": "dm-visual-analysis-v1",
        "preprocessing_version": "original-png-jpeg-bytes-v1",
        "frozen_baseline": "constant-no-visible-damage-v1",
        "development_sample_ids": [],
        "samples": samples,
    }
    manifest_path = tmp_path / "locked-release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, specification, damage_by_hash


@pytest.mark.asyncio
async def test_full_release_runs_actual_locked_pairs_and_reports_configuration(
    tmp_path: Path,
) -> None:
    manifest, specification, damage_by_hash = _stage_locked_slice(tmp_path)
    analyzer = LockedSliceFakeAnalyzer(damage_by_hash)

    result = await evaluate_locked_release(
        staged_root=tmp_path,
        manifest_path=manifest,
        specification_path=specification,
        analyzer=analyzer,
        evaluated_at=NOW,
    )

    assert result.passed
    assert result.sample_count == 10
    assert result.model_call_count == 7
    assert result.metrics["damage"]["macro_f1"] == 1
    assert result.metrics["vqa"]["abstention_rate"] == 1
    assert result.metrics["association"]["association_accuracy"] == 1
    assert result.metrics["map"]["provenance_completeness"] == 1
    assert result.model["maximum_output_tokens"] == 384
    assert result.model["temperature"] == 0
    assert result.model["seed"] == 7
    assert result.evaluation_runtime_seconds >= 0
    assert all("dataset_family" not in str(request) for request in analyzer.requests)


@pytest.mark.asyncio
async def test_full_release_rejects_majority_model_despite_safe_execution(
    tmp_path: Path,
) -> None:
    manifest, specification, damage_by_hash = _stage_locked_slice(tmp_path)

    result = await evaluate_locked_release(
        staged_root=tmp_path,
        manifest_path=manifest,
        specification_path=specification,
        analyzer=LockedSliceFakeAnalyzer(damage_by_hash, majority=True),
        evaluated_at=NOW,
    )

    assert result.metrics["damage"]["accuracy"] == 0.25
    assert result.metrics["damage"]["macro_f1"] < 0.85
    assert not result.capability_passed
    assert not result.passed


def test_preparation_rehashes_and_locks_complete_external_selection(
    tmp_path: Path,
) -> None:
    selection, specification, _ = _stage_locked_slice(tmp_path)

    locked = lock_manifest(tmp_path, selection, specification_path=specification)

    assert locked["manifest_version"] == "dm-mm-locked-v1"
    assert len(locked["samples"]) == 10
    assert all(len(item["sha256"]) == 64 for item in locked["samples"])
    assert locked["samples"] == sorted(
        locked["samples"], key=lambda item: item["sample_id"]
    )
