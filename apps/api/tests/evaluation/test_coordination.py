import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from test_decision_support import FIXTURES as DECISION_FIXTURES
from test_decision_support import _products

from disaster_monitor.application.services.collaborative_investigation import (
    SAFETY_POLICY_FINGERPRINT,
    CollaborativeInvestigator,
    single_supervisor_baseline,
    validate_collaborative_investigation,
)
from disaster_monitor.application.services.coordination_handoffs import (
    CoordinationHandoffPlanner,
    SpecialistHandoffBroker,
    role_permissions,
    task_owner,
    validate_specialist_handoff,
)
from disaster_monitor.domain.coordination import (
    CollaborativeInvestigationStatus,
    CoordinationPermission,
    SpecialistFinding,
    SpecialistRole,
)
from disaster_monitor.domain.multimodal import (
    AssetEligibility,
    AssetModality,
    CaptureRole,
    MultimodalAsset,
    MultimodalEvidenceState,
    MultimodalSourceMetadata,
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


def test_co_b_release_gate() -> None:
    fixture = json.loads(
        (FIXTURES / "collaboration_cases.v1.json").read_text(encoding="utf-8")
    )
    assert fixture["fixture_version"] == "dm-co-b-v1"
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases
    scenario_fixture = json.loads(
        (DECISION_FIXTURES / "scenario_cases.v1.json").read_text(encoding="utf-8")
    )
    scenarios = {str(item["id"]): item for item in scenario_fixture["cases"]}
    runs_per_case = int(fixture["runs_per_case"])
    investigator = CollaborativeInvestigator()
    planner = CoordinationHandoffPlanner()
    baseline_scores: list[float] = []
    collaborative_scores: list[float] = []
    unresolved_deadlocks = 0
    pass_eight = 0

    for item in cases:
        assert isinstance(item, dict)
        state, _hypotheses, _priority, _triage, artifact = _products(
            scenarios[str(item["scenario_id"])]
        )
        multimodal = (
            _multimodal_state(state, str(item["id"])) if item["multimodal"] else None
        )
        handoffs = (
            planner.for_evidence_state(state),
            planner.for_decision_support(artifact),
            *(
                (planner.for_multimodal_state(multimodal),)
                if multimodal is not None
                else ()
            ),
        )
        expected = dict(item["expected"])
        expected.update(
            {
                "event_identity": state.physical_event.physical_event_id,
                "decision_policy": SAFETY_POLICY_FINGERPRINT,
            }
        )
        if multimodal is not None:
            expected["multimodal_provenance"] = multimodal.state_version
        baseline_scores.append(
            _end_state_score(single_supervisor_baseline(state), expected)
        )
        run_success: list[bool] = []
        for run in range(runs_per_case):
            ordered_handoffs = handoffs if run % 2 == 0 else tuple(reversed(handoffs))
            result = investigator.investigate(
                state,
                ordered_handoffs,
                decision_support=artifact,
                multimodal_state=multimodal,
            )
            actual = {finding.finding_key: finding.value for finding in result.findings}
            score = _end_state_score(actual, expected)
            collaborative_scores.append(score)
            unresolved_deadlocks += bool(result.unresolved_deadlocks)
            run_success.append(
                result.status == CollaborativeInvestigationStatus.COMPLETED
                and score == 1.0
                and result.safety_policy_fingerprint == SAFETY_POLICY_FINGERPRINT
            )
            validate_collaborative_investigation(
                result,
                state=state,
                decision_support=artifact,
                multimodal_state=multimodal,
            )
        pass_eight += all(run_success)

    baseline_score = sum(baseline_scores) / len(baseline_scores)
    collaborative_score = sum(collaborative_scores) / len(collaborative_scores)
    improvement = collaborative_score - baseline_score
    deadlock_rate = unresolved_deadlocks / (len(cases) * runs_per_case)
    pass_eight_rate = pass_eight / len(cases)
    assert improvement >= 0.10, ("co_b.end_state_improvement", improvement)
    assert deadlock_rate <= 0.05, ("co_b.unresolved_deadlocks", deadlock_rate)
    assert pass_eight_rate >= 0.85, ("co_b.pass8", pass_eight_rate)


def test_co_b_attacks_fall_back_without_policy_or_evidence_mutation() -> None:
    scenario_fixture = json.loads(
        (DECISION_FIXTURES / "scenario_cases.v1.json").read_text(encoding="utf-8")
    )
    scenario = next(
        item for item in scenario_fixture["cases"] if item["id"] == "positive-injuries"
    )
    state, _hypotheses, _priority, _triage, artifact = _products(scenario)
    planner = CoordinationHandoffPlanner()
    handoffs = (
        planner.for_evidence_state(state),
        planner.for_decision_support(artifact),
    )
    investigator = CollaborativeInvestigator()
    evidence_id = state.physical_event.physical_event_id
    source_id = state.physical_event.event.source.source_id

    loop = investigator.investigate(
        state, handoffs, decision_support=artifact, requested_iterations=3
    )
    assert loop.status == CollaborativeInvestigationStatus.SINGLE_SUPERVISOR_FALLBACK
    assert loop.fallback_reason == "iteration_budget_exceeded"

    altered_policy = _injected_finding(
        state.state_version,
        evidence_id,
        source_id,
        key="safety_override",
        value="allowed",
        fingerprint="altered-policy",
    )
    collusion = investigator.investigate(
        state,
        handoffs,
        decision_support=artifact,
        injected_findings=(altered_policy,),
    )
    assert collusion.fallback_reason == "finding_authority_or_provenance_violation"

    mutated_evidence = _injected_finding(
        state.state_version,
        "evidence:not-present",
        source_id,
        key="invented_evidence",
        value="accepted",
    )
    mutation = investigator.investigate(
        state,
        handoffs,
        decision_support=artifact,
        injected_findings=(mutated_evidence,),
    )
    assert mutation.fallback_reason == "finding_authority_or_provenance_violation"

    deadlock_finding = _injected_finding(
        state.state_version,
        evidence_id,
        source_id,
        key="recommendation_status",
        value="bypass",
    )
    deadlock = investigator.investigate(
        state,
        handoffs,
        decision_support=artifact,
        injected_findings=(deadlock_finding,),
    )
    assert deadlock.fallback_reason == "specialist_deadlock"
    assert deadlock.unresolved_deadlocks == ("recommendation_status",)
    assert single_supervisor_baseline(state) == {
        "event_identity": state.physical_event.physical_event_id
    }


def _end_state_score(actual: dict[str, str], expected: dict[str, str]) -> float:
    return sum(actual.get(key) == value for key, value in expected.items()) / len(
        expected
    )


def _multimodal_state(state, case_id: str) -> MultimodalEvidenceState:
    content = b"frozen-co-b-asset"
    asset = MultimodalAsset(
        asset_id=f"asset:{case_id}",
        source=MultimodalSourceMetadata(
            source_id=f"operator-asset:{case_id}",
            attribution="Frozen CO-B operator asset",
        ),
        retrieved_at=NOW,
        captured_at=NOW,
        modality=AssetModality.IMAGE,
        media_type="image/png",
        content_sha256=hashlib.sha256(content).hexdigest(),
        byte_length=len(content),
        width=1,
        height=1,
        footprint=None,
        declared_hazard=state.physical_event.event.hazard,
        declared_country_code=state.physical_event.event.country.alpha3_code,
        capture_role=CaptureRole.SINGLE_CAPTURE,
        processing_level="raw",
        parent_asset_ids=(),
        event_id_hint=state.physical_event.event.event_id,
        eligibility=AssetEligibility.ANALYSIS_ELIGIBLE,
        eligibility_reasons=("frozen-co-b",),
        content=content,
    )
    return MultimodalEvidenceState(
        state_version=f"multimodal:{case_id}",
        evidence_world_state_version=state.state_version,
        physical_event_id=state.physical_event.physical_event_id,
        assets=(asset,),
        associations=(),
        observations=(),
        evaluated_at=NOW,
    )


def _injected_finding(
    state_version: str,
    evidence_id: str,
    source_id: str,
    *,
    key: str,
    value: str,
    fingerprint: str = SAFETY_POLICY_FINGERPRINT,
) -> SpecialistFinding:
    return SpecialistFinding(
        finding_id=f"finding:injected:{key}",
        specialist_role=SpecialistRole.DECISION_ANALYSIS,
        finding_key=key,
        value=value,
        summary="Frozen adversarial specialist finding.",
        state_version=state_version,
        evidence_ids=(evidence_id,),
        source_ids=(source_id,),
        safety_policy_fingerprint=fingerprint,
    )
