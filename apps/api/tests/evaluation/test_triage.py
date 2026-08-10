import json
from pathlib import Path

from disaster_monitor.application.agent.models import InformationNeed
from disaster_monitor.application.agent.task_normalization import (
    deterministic_task_draft,
    disaster_safety_gate,
)

FIXTURES = Path(__file__).parent / "fixtures" / "triage"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _f1(*, true_positive: int, false_positive: int, false_negative: int) -> float:
    denominator = 2 * true_positive + false_positive + false_negative
    return 1.0 if denominator == 0 else 2 * true_positive / denominator


def test_tr_a_release_gate() -> None:
    fixture = _load("information_need_cases.v1.json")
    assert fixture["fixture_version"] == "dm-tr-a-v1"
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases

    label_counts = {
        need: {"true_positive": 0, "false_positive": 0, "false_negative": 0}
        for need in InformationNeed
    }
    evidence_true_positive = 0
    evidence_false_negative = 0

    for item in cases:
        assert isinstance(item, dict)
        case_id = str(item["id"])
        text = str(item["text"])
        expected = {InformationNeed(value) for value in item["needs"]}
        predicted = {
            InformationNeed(value)
            for value in deterministic_task_draft(text).information_needs
        }
        for label, counts in label_counts.items():
            if label in expected and label in predicted:
                counts["true_positive"] += 1
            elif label not in expected and label in predicted:
                counts["false_positive"] += 1
            elif label in expected and label not in predicted:
                counts["false_negative"] += 1
        if bool(item["requires_evidence"]):
            if disaster_safety_gate(text):
                evidence_true_positive += 1
            else:
                evidence_false_negative += 1
        assert predicted == expected, case_id

    label_f1 = {label.value: _f1(**counts) for label, counts in label_counts.items()}
    macro_f1 = sum(label_f1.values()) / len(label_f1)
    evidence_recall = evidence_true_positive / (
        evidence_true_positive + evidence_false_negative
    )

    assert macro_f1 >= 0.95, ("tr_a.information_need_macro_f1", label_f1)
    assert evidence_recall >= 0.99, (
        "tr_a.requires_evidence_recall",
        evidence_recall,
    )
    assert all(
        disaster_safety_gate(str(item["text"])) == bool(item["requires_evidence"])
        for item in cases
    )


def test_tr_a_is_deterministic_across_order_and_repeated_runs() -> None:
    cases = _load("information_need_cases.v1.json")["cases"]
    assert isinstance(cases, list)

    baseline = {
        str(item["id"]): deterministic_task_draft(str(item["text"])) for item in cases
    }
    for replay in range(8):
        ordered = cases if replay % 2 == 0 else tuple(reversed(cases))
        assert {
            str(item["id"]): deterministic_task_draft(str(item["text"]))
            for item in ordered
        } == baseline
