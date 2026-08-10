import json
from copy import deepcopy
from pathlib import Path

import pytest

from disaster_monitor.evaluation.operator_study import (
    OperatorStudyError,
    score_operator_study,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "multimodal"
    / "operator_study_protocol.v1.json"
)


def _protocol() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _results() -> dict:
    protocol = _protocol()
    records = []
    expertise = protocol["expertise_categories"]
    for index in range(6):
        sequence_name = "A" if index % 2 == 0 else "B"
        for period, assignment in enumerate(
            protocol["counterbalance_sequences"][sequence_name], start=1
        ):
            is_cop = assignment["condition"] == "cop"
            text_success = index < 2
            completed = is_cop or text_success
            records.append(
                {
                    "participant_code": f"study-{index + 1:02d}",
                    "expertise_category": expertise[index % len(expertise)],
                    "sequence": sequence_name,
                    "period": period,
                    **assignment,
                    "task_completed": completed,
                    "critical_error_codes": (
                        [] if completed else ["missed_visible_access_impact"]
                    ),
                    "completion_seconds": 240 + index,
                    "substantive_corrections": 0 if completed else 1,
                }
            )
    return {
        "protocol_version": protocol["protocol_version"],
        "result_set_id": "operator-study-run-001",
        "data_origin": "human_operator_study",
        "human_participation_attested": True,
        "records": records,
    }


def test_operator_gate_scores_paired_counterbalanced_primary_outcome() -> None:
    score = score_operator_study(_protocol(), _results())

    assert score.participant_count == 6
    assert score.sequence_counts == {"A": 3, "B": 3}
    assert score.text_only.completion_rate == pytest.approx(2 / 6)
    assert score.cop.completion_rate == 1
    assert score.absolute_task_completion_improvement == pytest.approx(4 / 6)
    assert score.passed


def test_operator_gate_rejects_simulated_or_unattested_people() -> None:
    results = _results()
    results["data_origin"] = "simulated_users"

    with pytest.raises(OperatorStudyError, match="simulated"):
        score_operator_study(_protocol(), results)

    results = _results()
    results["human_participation_attested"] = False
    with pytest.raises(OperatorStudyError, match="attested"):
        score_operator_study(_protocol(), results)


def test_operator_gate_rejects_incomplete_or_unbalanced_pairing() -> None:
    incomplete = _results()
    incomplete["records"].pop()
    with pytest.raises(OperatorStudyError, match="exactly two"):
        score_operator_study(_protocol(), incomplete)

    unbalanced = _results()
    protocol = _protocol()
    for record in unbalanced["records"]:
        participant = int(record["participant_code"].removeprefix("study-"))
        if participant % 2 == 0:
            assignment = protocol["counterbalance_sequences"]["A"][record["period"] - 1]
            record.update(sequence="A", **assignment)
    with pytest.raises(OperatorStudyError, match="counterbalanced"):
        score_operator_study(protocol, unbalanced)


def test_operator_gate_rejects_personal_information() -> None:
    results = deepcopy(_results())
    results["records"][0]["email"] = "not-allowed@example.test"

    with pytest.raises(OperatorStudyError, match="personal"):
        score_operator_study(_protocol(), results)


def test_frozen_protocol_truthfully_records_pending_human_status() -> None:
    protocol = _protocol()

    assert protocol["status"] == "awaiting_legitimate_human_results"
    assert protocol["primary_outcome"] == "task_completed_without_critical_error"
    assert "human_only" in protocol["collection_rules"]
