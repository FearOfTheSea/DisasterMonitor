import json
from datetime import UTC, datetime
from pathlib import Path

from disaster_monitor.application.services.coordination_handoffs import (
    SpecialistHandoffBroker,
    role_permissions,
    task_owner,
    validate_specialist_handoff,
)
from disaster_monitor.domain.coordination import (
    CoordinationPermission,
    SpecialistRole,
)

FIXTURES = Path(__file__).parent / "fixtures" / "coordination"
NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


def _load() -> dict[str, object]:
    return json.loads((FIXTURES / "handoff_cases.v1.json").read_text(encoding="utf-8"))


def test_co_a_release_gate() -> None:
    fixture = _load()
    assert fixture["fixture_version"] == "dm-co-a-v1"
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases
    broker = SpecialistHandoffBroker()
    schema_correct = 0
    provenance_passed = 0
    provenance_total = 0
    ownership_passed = 0
    ownership_total = 0
    privilege_escalations = 0

    for item in cases:
        assert isinstance(item, dict)
        payload = item["payload"]
        assert isinstance(payload, dict)
        handoff = None
        try:
            handoff = broker.parse_and_issue(payload, issued_at=NOW)
        except ValueError:
            pass
        accepted = handoff is not None
        schema_correct += accepted is bool(item["expect_accept"])
        if handoff is None:
            continue
        validate_specialist_handoff(handoff)
        for reference in handoff.artifact_references:
            provenance_total += 1
            provenance_passed += bool(
                reference.artifact_id
                and reference.state_version
                and reference.evidence_ids
                and reference.source_ids
            )
        ownership_total += 1
        ownership_passed += (
            handoff.owner_role == task_owner(handoff.task_type)
            and handoff.receiver_role == handoff.owner_role
            and handoff.owner_role == SpecialistRole(str(item["expected_owner"]))
        )
        privilege_escalations += not set(handoff.granted_permissions) <= set(
            role_permissions(handoff.receiver_role)
        )

    schema_validity = schema_correct / len(cases)
    provenance_rate = provenance_passed / provenance_total
    ownership_rate = ownership_passed / ownership_total
    assert schema_validity >= 0.995, ("co_a.schema_validity", schema_validity)
    assert provenance_rate == 1.0, ("co_a.provenance", provenance_rate)
    assert privilege_escalations == 0, (
        "co_a.privilege_escalations",
        privilege_escalations,
    )
    assert ownership_rate >= 0.99, ("co_a.task_ownership", ownership_rate)


def test_co_a_is_deterministic_and_never_inherits_sender_permissions() -> None:
    cases = _load()["cases"]
    assert isinstance(cases, list)
    valid = [item for item in cases if item["expect_accept"]]
    broker = SpecialistHandoffBroker()
    baseline = {
        str(item["id"]): broker.parse_and_issue(item["payload"], issued_at=NOW)
        for item in valid
    }
    for run in range(8):
        ordered = valid if run % 2 == 0 else tuple(reversed(valid))
        assert {
            str(item["id"]): broker.parse_and_issue(item["payload"], issued_at=NOW)
            for item in ordered
        } == baseline

    event_handoff = baseline["valid-event-identity"]
    assert event_handoff.sender_role == SpecialistRole.SUPERVISOR
    assert set(event_handoff.granted_permissions) <= set(
        role_permissions(SpecialistRole.EVENT_IDENTITY)
    )
    assert CoordinationPermission.READ_DECISION_SUPPORT not in (
        event_handoff.granted_permissions
    )
    assert CoordinationPermission.EXECUTE_PROVIDER_IO not in (
        event_handoff.granted_permissions
    )
    assert CoordinationPermission.ALTER_SAFETY_POLICY not in (
        event_handoff.granted_permissions
    )
