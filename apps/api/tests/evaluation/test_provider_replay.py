import json
from pathlib import Path

import pytest

from disaster_monitor.evaluation.provider_replay import (
    REQUIRED_HAZARDS,
    load_provider_corpus,
    replay_provider_corpus,
)
from disaster_monitor.evaluation.reproducibility import ReproducibilityError

REPOSITORY_ROOT = Path(__file__).parents[4]
CORPUS_PATH = REPOSITORY_ROOT / "evaluation" / "provider_reference_corpus.v1.json"
ADVERSARIAL_PATH = REPOSITORY_ROOT / "evaluation" / "adversarial_identity_cases.v1.json"


def test_locked_provider_corpus_covers_all_hazards_and_replays_deterministically() -> (
    None
):
    document, cases = load_provider_corpus(CORPUS_PATH)
    assert document["no_network_replay"] is True
    assert {case.hazard for case in cases} == REQUIRED_HAZARDS

    first = replay_provider_corpus(CORPUS_PATH)
    second = replay_provider_corpus(CORPUS_PATH)

    assert first == second
    assert first.deterministic is True
    assert first.promotion_eligible is True
    assert all(item.recall == 1 for item in first.metrics)


def test_provider_replay_fails_closed_when_snapshot_checksum_changes(
    tmp_path: Path,
) -> None:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    snapshot_path = tmp_path / "snapshot.json"
    original_snapshot = (
        REPOSITORY_ROOT / "evaluation" / "provider_payload_snapshots.v1.json"
    ).read_text(encoding="utf-8")
    snapshot_path.write_text(original_snapshot + "\n", encoding="utf-8")
    for case in corpus["cases"]:
        case["payload_path"] = "snapshot.json"
    altered_path = tmp_path / "corpus.json"
    altered_path.write_text(json.dumps(corpus), encoding="utf-8")

    with pytest.raises(ReproducibilityError, match="checksum mismatch"):
        replay_provider_corpus(altered_path)


def test_adversarial_identity_corpus_keeps_required_categories_locked() -> None:
    document = json.loads(ADVERSARIAL_PATH.read_text(encoding="utf-8"))
    categories = {item["category"] for item in document["cases"]}
    assert categories == {
        "nearby_earthquakes",
        "repeated_storm_names",
        "cross_border",
        "antimeridian",
        "same_day_volcano_updates",
        "duplicates_and_corrections",
    }
    assert all(
        item["expected_decision"] and item["reason"] for item in document["cases"]
    )
