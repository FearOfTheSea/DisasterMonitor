"""Reproducible, non-PII scoring for the paired MM-C operator study."""

from dataclasses import asdict, dataclass
from typing import Any


class OperatorStudyError(RuntimeError):
    """A protocol, integrity, or legitimate-human-evidence failure."""


@dataclass(frozen=True, slots=True)
class ConditionScore:
    completed_without_critical_error: int
    total: int
    completion_rate: float


@dataclass(frozen=True, slots=True)
class OperatorStudyScore:
    protocol_version: str
    result_set_id: str
    participant_count: int
    expertise_counts: dict[str, int]
    sequence_counts: dict[str, int]
    text_only: ConditionScore
    cop: ConditionScore
    absolute_task_completion_improvement: float
    critical_error_count: int
    substantive_correction_count: int
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_operator_study(
    protocol: dict[str, Any], results: dict[str, Any]
) -> OperatorStudyScore:
    """Score genuine paired records against the frozen primary outcome."""
    _validate_protocol(protocol)
    _reject_personal_information(results)
    if results.get("protocol_version") != protocol["protocol_version"]:
        raise OperatorStudyError("result protocol version does not match the freeze")
    if results.get("data_origin") != "human_operator_study":
        raise OperatorStudyError(
            "simulated or model-generated users cannot satisfy MM-C"
        )
    if results.get("human_participation_attested") is not True:
        raise OperatorStudyError("human participation must be explicitly attested")
    result_set_id = results.get("result_set_id")
    if not isinstance(result_set_id, str) or not result_set_id.strip():
        raise OperatorStudyError("results require a stable non-personal result_set_id")
    records = results.get("records")
    if not isinstance(records, list) or not records:
        raise OperatorStudyError("operator results contain no task records")
    if any(not isinstance(item, dict) for item in records):
        raise OperatorStudyError("each operator task record must be an object")
    typed_records: list[dict[str, Any]] = records

    allowed_expertise = set(protocol["expertise_categories"])
    sequences: dict[str, list[dict[str, str]]] = protocol["counterbalance_sequences"]
    by_participant: dict[str, list[dict[str, Any]]] = {}
    for record in typed_records:
        _validate_record(record, allowed_expertise, sequences)
        code = str(record["participant_code"])
        by_participant.setdefault(code, []).append(record)

    minimum = int(protocol["minimum_participants"])
    if len(by_participant) < minimum:
        raise OperatorStudyError(
            f"operator study requires at least {minimum} legitimate participants"
        )
    sequence_counts = {name: 0 for name in sequences}
    expertise_counts = {name: 0 for name in sorted(allowed_expertise)}
    for participant_records in by_participant.values():
        sequence = _validate_participant_pair(participant_records, sequences)
        sequence_counts[sequence] += 1
        expertise = str(participant_records[0]["expertise_category"])
        if any(item["expertise_category"] != expertise for item in participant_records):
            raise OperatorStudyError(
                "expertise category changed within one participant"
            )
        expertise_counts[expertise] += 1
    if any(count == 0 for count in sequence_counts.values()) or (
        max(sequence_counts.values()) - min(sequence_counts.values()) > 1
    ):
        raise OperatorStudyError("condition ordering is not properly counterbalanced")

    text = _condition_score(typed_records, "text_only")
    cop = _condition_score(typed_records, "cop")
    improvement = cop.completion_rate - text.completion_rate
    if protocol["acceptance_rule"] != "cop_completion_rate_strictly_greater":
        raise OperatorStudyError("operator protocol acceptance rule is unsupported")
    return OperatorStudyScore(
        protocol_version=str(protocol["protocol_version"]),
        result_set_id=result_set_id.strip(),
        participant_count=len(by_participant),
        expertise_counts=expertise_counts,
        sequence_counts=sequence_counts,
        text_only=text,
        cop=cop,
        absolute_task_completion_improvement=improvement,
        critical_error_count=sum(
            bool(item["critical_error_codes"]) for item in typed_records
        ),
        substantive_correction_count=sum(
            int(item["substantive_corrections"]) for item in typed_records
        ),
        passed=improvement > 0,
    )


def _validate_protocol(protocol: dict[str, Any]) -> None:
    if protocol.get("protocol_version") != "dm-mm-c-operator-v1":
        raise OperatorStudyError("operator protocol version is not supported")
    if protocol.get("primary_outcome") != "task_completed_without_critical_error":
        raise OperatorStudyError("the frozen primary outcome is missing")
    if (
        not isinstance(protocol.get("minimum_participants"), int)
        or protocol["minimum_participants"] < 2
    ):
        raise OperatorStudyError("operator protocol has no defensible minimum sample")
    expertise = protocol.get("expertise_categories")
    if not isinstance(expertise, list) or not expertise:
        raise OperatorStudyError("operator expertise categories are missing")
    sequences = protocol.get("counterbalance_sequences")
    if not isinstance(sequences, dict) or set(sequences) != {"A", "B"}:
        raise OperatorStudyError("operator protocol requires two frozen sequences")
    for sequence in sequences.values():
        if (
            not isinstance(sequence, list)
            or len(sequence) != 2
            or {item.get("condition") for item in sequence} != {"text_only", "cop"}
        ):
            raise OperatorStudyError("each sequence requires both study conditions")


def _validate_record(
    record: dict[str, Any],
    allowed_expertise: set[str],
    sequences: dict[str, list[dict[str, str]]],
) -> None:
    required = {
        "participant_code",
        "expertise_category",
        "sequence",
        "period",
        "scenario_id",
        "scenario_version",
        "condition",
        "task_completed",
        "critical_error_codes",
        "completion_seconds",
        "substantive_corrections",
    }
    missing = required - set(record)
    if missing:
        raise OperatorStudyError(
            f"operator record is missing fields: {sorted(missing)}"
        )
    code = record["participant_code"]
    if not isinstance(code, str) or not code.strip() or len(code) > 40:
        raise OperatorStudyError("participant_code must be a bounded non-personal code")
    if record["expertise_category"] not in allowed_expertise:
        raise OperatorStudyError("operator expertise category is outside the protocol")
    sequence_name = record["sequence"]
    period = record["period"]
    if sequence_name not in sequences or period not in {1, 2}:
        raise OperatorStudyError("operator sequence or period is invalid")
    expected = sequences[sequence_name][period - 1]
    if any(record.get(field) != expected[field] for field in expected):
        raise OperatorStudyError(
            "operator record violates its counterbalanced assignment"
        )
    if not isinstance(record["task_completed"], bool):
        raise OperatorStudyError("task_completed must be human-recorded boolean data")
    errors = record["critical_error_codes"]
    if not isinstance(errors, list) or any(
        not isinstance(item, str) for item in errors
    ):
        raise OperatorStudyError("critical_error_codes must be a string list")
    seconds = record["completion_seconds"]
    if seconds is not None and (
        isinstance(seconds, bool)
        or not isinstance(seconds, int | float)
        or seconds <= 0
    ):
        raise OperatorStudyError("completion_seconds must be positive or null")
    corrections = record["substantive_corrections"]
    if (
        isinstance(corrections, bool)
        or not isinstance(corrections, int)
        or corrections < 0
    ):
        raise OperatorStudyError("substantive_corrections must be a non-negative count")


def _validate_participant_pair(
    records: list[dict[str, Any]], sequences: dict[str, list[dict[str, str]]]
) -> str:
    if len(records) != 2:
        raise OperatorStudyError(
            "each participant requires exactly two paired task records"
        )
    sequence_names = {str(item["sequence"]) for item in records}
    if len(sequence_names) != 1:
        raise OperatorStudyError("participant records use inconsistent sequences")
    sequence = next(iter(sequence_names))
    observed = {
        (
            int(item["period"]),
            str(item["scenario_id"]),
            str(item["scenario_version"]),
            str(item["condition"]),
        )
        for item in records
    }
    expected = {
        (
            period,
            item["scenario_id"],
            item["scenario_version"],
            item["condition"],
        )
        for period, item in enumerate(sequences[sequence], start=1)
    }
    if observed != expected:
        raise OperatorStudyError("participant pair is incomplete or duplicated")
    return sequence


def _condition_score(records: list[dict[str, Any]], condition: str) -> ConditionScore:
    selected = [item for item in records if item["condition"] == condition]
    completed = sum(
        item["task_completed"] and not item["critical_error_codes"] for item in selected
    )
    if not selected:
        raise OperatorStudyError(f"operator results contain no {condition} records")
    return ConditionScore(completed, len(selected), completed / len(selected))


def _reject_personal_information(value: Any) -> None:
    prohibited_keys = {
        "name",
        "email",
        "phone",
        "address",
        "employer",
        "organization",
        "ip_address",
        "birth_date",
    }
    if isinstance(value, dict):
        keys = {str(key).casefold() for key in value}
        found = keys & prohibited_keys
        if found:
            raise OperatorStudyError(
                f"operator results contain prohibited personal fields: {sorted(found)}"
            )
        for item in value.values():
            _reject_personal_information(item)
    elif isinstance(value, list):
        for item in value:
            _reject_personal_information(item)
