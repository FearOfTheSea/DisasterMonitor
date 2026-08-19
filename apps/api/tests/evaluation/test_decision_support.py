import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from evidence_world_state_metrics import expected_calibration_error

from disaster_monitor.application.services.decision_autonomy import (
    DecisionAutonomyController,
    validate_decision_execution,
)
from disaster_monitor.application.services.decision_support import (
    DecisionOptionGenerator,
    render_decision_support,
    validate_decision_support_artifact,
)
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_state import (
    build_evidence_world_state,
)
from disaster_monitor.application.services.hypothesis_reasoning import (
    HypothesisGenerator,
)
from disaster_monitor.application.services.incident_priority import (
    IncidentPriorityRanker,
)
from disaster_monitor.application.services.scenario_reasoning import (
    validate_scenario_analysis,
)
from disaster_monitor.application.services.triage_autonomy import TriageAutonomyPolicy
from disaster_monitor.domain.decision import (
    PROHIBITED_CONSEQUENTIAL_ACTIONS,
    DecisionAutonomyMode,
    DecisionConsequence,
    DecisionExecutionState,
    DecisionFact,
    DecisionInternalAction,
    DecisionRecommendationStatus,
    DecisionScenarioMode,
    DecisionStatementType,
)
from disaster_monitor.domain.disaster import (
    Disaster,
    DisasterEvent,
    EventMeasurement,
    EvidenceDisposition,
    FactStatus,
    MeasurementKind,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

FIXTURES = Path(__file__).parent / "fixtures" / "decision_support"
NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
COUNTRIES = StaticCountryCatalog()


def _load() -> dict[str, object]:
    return json.loads((FIXTURES / "option_cases.v1.json").read_text(encoding="utf-8"))


def _state(item: dict[str, object]):
    case_id = str(item["id"])
    disaster = Disaster(str(item["disaster"]))
    country = COUNTRIES.get_by_alpha3(str(item["country_code"]))
    assert country is not None
    event_time = datetime(2026, 8, 11, 6, tzinfo=UTC)
    event_source = SourceReference(
        source_id=f"event-{case_id}",
        publisher="Frozen event source",
        title=f"Event {case_id}",
        canonical_url=f"https://events.example/{case_id}",
        published_at=event_time,
        updated_at=None,
        retrieved_at=NOW,
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    event = DisasterEvent(
        event_id=case_id,
        disaster=disaster,
        location=country.canonical_name,
        country=country,
        event_time=event_time,
        source=event_source,
        measurements=(
            ()
            if item.get("magnitude") is None
            else (
                EventMeasurement(
                    MeasurementKind.MAGNITUDE,
                    float(item["magnitude"]),
                    source=event_source,
                ),
            )
        ),
    )
    physical_event = (
        default_event_policy_registry()
        .for_disaster(disaster)
        .identify((event,))
        .physical_events[0]
    )
    raw_reports = item.get("reports")
    if raw_reports is None:
        raw_reports = (
            []
            if not item.get("facts")
            else [{"source_id": f"report-{case_id}", "facts": item["facts"]}]
        )
    assert isinstance(raw_reports, list)
    reports: list[SituationReport] = []
    for raw_report in raw_reports:
        assert isinstance(raw_report, dict)
        source_id = str(raw_report["source_id"])
        source_time = NOW - timedelta(hours=float(raw_report.get("hours_ago", 0)))
        source = SourceReference(
            source_id=source_id,
            publisher=f"Authority {source_id}",
            title=f"Situation {source_id}",
            canonical_url=f"https://reports.example/{case_id}/{source_id}",
            published_at=source_time,
            updated_at=None,
            retrieved_at=NOW,
            authority=SourceAuthority.NATIONAL_AUTHORITY,
        )
        raw_facts = raw_report["facts"]
        assert isinstance(raw_facts, list)
        facts = tuple(
            ReportedFact(
                category=str(fact["category"]),
                label=str(fact["category"]).replace("_", " ").title(),
                value=str(fact["value"]),
                status=FactStatus(str(fact.get("status", "confirmed"))),
                source=source,
                event_id=case_id,
                claim_id=str(fact["category"]),
            )
            for fact in raw_facts
        )
        reports.append(
            SituationReport(
                source=source,
                narrative="Frozen decision-support packet.",
                facts=facts,
                event_id=case_id,
                disaster=disaster,
                country_codes=(country.alpha3_code,),
            )
        )
    return build_evidence_world_state(
        event,
        tuple(reports),
        evaluated_at=NOW,
        physical_event=physical_event,
    )


def _products(item: dict[str, object]):
    state = _state(item)
    hypotheses = HypothesisGenerator().generate(state)
    priority = IncidentPriorityRanker().assess(state)
    triage = TriageAutonomyPolicy().decide(priority)
    artifact = DecisionOptionGenerator().generate(state, hypotheses, priority, triage)
    return state, hypotheses, priority, triage, artifact


def test_ds_a_release_gate() -> None:
    fixture = _load()
    assert fixture["fixture_version"] == "dm-ds-a-v1"
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases
    factual_support_passed = 0
    factual_support_total = 0
    trace_passed = 0
    trace_total = 0
    relevance_passed = 0

    for item in cases:
        state, hypotheses, priority, triage, artifact = _products(item)
        known_evidence_ids = {
            state.physical_event.physical_event_id,
            *(
                history.observation.observation_id
                for claim in state.claims
                for history in claim.history
            ),
        }
        known_source_ids = {
            state.physical_event.event.source.source_id,
            *(
                history.observation.fact.source.source_id
                for claim in state.claims
                for history in claim.history
            ),
        }
        for fact in artifact.facts:
            factual_support_total += 1
            factual_support_passed += (
                set(fact.evidence_ids) <= known_evidence_ids
                and set(fact.source_ids) <= known_source_ids
            )
        fact_ids = {fact.fact_id for fact in artifact.facts}
        estimate_ids = {estimate.estimate_id for estimate in artifact.estimates}
        assumption_ids = {
            assumption.assumption_id for assumption in artifact.assumptions
        }
        for option in artifact.options:
            trace_total += 1
            trace_passed += (
                bool(
                    option.supporting_fact_ids
                    or option.supporting_estimate_ids
                    or option.assumption_ids
                )
                and set(option.supporting_fact_ids) <= fact_ids
                and set(option.supporting_estimate_ids) <= estimate_ids
                and set(option.assumption_ids) <= assumption_ids
            )
        expected = set(item["expected_options"])
        actual = {option.option_kind for option in artifact.options}
        relevance_passed += actual == expected
        assert artifact.advisory_only
        assert all(
            fact.statement_type == DecisionStatementType.VERIFIED_FACT
            for fact in artifact.facts
        )
        assert all(
            estimate.statement_type == DecisionStatementType.ESTIMATE
            for estimate in artifact.estimates
        )
        assert all(
            assumption.statement_type == DecisionStatementType.ASSUMPTION
            for assumption in artifact.assumptions
        )
        assert all(
            option.statement_type == DecisionStatementType.OPTION
            for option in artifact.options
        )
        validate_decision_support_artifact(
            artifact,
            state=state,
            hypotheses=hypotheses,
            priority=priority,
            triage=triage,
        )

    factual_support_rate = factual_support_passed / factual_support_total
    trace_rate = trace_passed / trace_total
    relevance_rate = relevance_passed / len(cases)
    assert factual_support_rate >= 0.995, (
        "ds_a.factual_support",
        factual_support_rate,
    )
    assert trace_rate == 1.0, ("ds_a.material_trace", trace_rate)
    assert relevance_rate >= 0.90, ("ds_a.option_relevance", relevance_rate)


def test_ds_epistemic_status_truth_table_and_hypothesis_policy() -> None:
    fixture = json.loads(
        (FIXTURES / "epistemic_status_cases.v1.json").read_text(encoding="utf-8")
    )
    assert fixture["fixture_version"] == "dm-ds-epistemic-v1"
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases

    for item in cases:
        state, hypotheses, _priority, _triage, artifact = _products(item)
        hypothesis = hypotheses[0]
        expected_fact_types = item["expected_fact_types"]
        assert isinstance(expected_fact_types, dict)
        actual_fact_types = {
            fact.status: fact.statement_type.value
            for fact in artifact.facts
            if fact.status != "source_backed_event"
        }
        assert actual_fact_types == expected_fact_types, item["id"]
        assert hypothesis.probability == pytest.approx(
            float(item["expected_probability"])
        ), item["id"]
        assert artifact.scenario_analysis.mode == DecisionScenarioMode(
            str(item["expected_mode"])
        )
        assert (
            artifact.scenario_analysis.recommendation.status
            == DecisionRecommendationStatus(str(item["expected_recommendation"]))
        )

        status_by_evidence_id = {
            history.observation.observation_id: history.observation.fact.status.value
            for claim in state.claims
            for history in claim.history
        }
        uncertain_statuses = {
            status_by_evidence_id[evidence_id]
            for evidence_id in hypothesis.uncertain_evidence_ids
        }
        assert uncertain_statuses == set(item["expected_uncertain_statuses"])
        assert all(
            any(status in feature.rule_id for feature in hypothesis.rationale_features)
            for status in uncertain_statuses
        )

        rendered = render_decision_support(artifact)
        for status, statement_type in expected_fact_types.items():
            assert f"[{statement_type}; status={status}]" in rendered
        assert "DM analytical estimate [estimate; inferred]" in rendered
        assert all(
            estimate.statement_type == DecisionStatementType.ESTIMATE
            for estimate in artifact.estimates
        )
        if "estimated" in expected_fact_types:
            assert actual_fact_types["estimated"] == "source_estimate"
            assert artifact.estimates[0].statement_type.value == "estimate"


def test_ds_domain_rejects_source_status_promotion_to_verified_fact() -> None:
    fixture = json.loads(
        (FIXTURES / "epistemic_status_cases.v1.json").read_text(encoding="utf-8")
    )
    cases = fixture["cases"]
    assert isinstance(cases, list)
    preliminary = next(item for item in cases if item["id"] == "preliminary-positive")
    artifact = _products(preliminary)[-1]
    fact = next(item for item in artifact.facts if item.status == "preliminary")

    with pytest.raises(ValueError, match="preserve source status"):
        replace(fact, statement_type=DecisionStatementType.VERIFIED_FACT)


def test_ds_a_rejects_unsupported_fact_and_omitted_contradiction() -> None:
    cases = _load()["cases"]
    assert isinstance(cases, list)
    conflict_case = next(
        item for item in cases if item["id"] == "conflicting-fatalities"
    )
    state, hypotheses, priority, triage, artifact = _products(conflict_case)
    fabricated = DecisionFact(
        fact_id="decision-fact:fabricated",
        statement="Unsupported current fatality total.",
        evidence_ids=("evidence:not-present",),
        source_ids=("source:not-present",),
        status="confirmed",
    )

    with pytest.raises(ValueError, match="lacks canonical"):
        validate_decision_support_artifact(
            replace(artifact, facts=(*artifact.facts, fabricated)),
            state=state,
            hypotheses=hypotheses,
            priority=priority,
            triage=triage,
        )
    assert any(
        item.disposition == EvidenceDisposition.CONFLICTING
        for claim in state.claims
        for item in claim.history
    )
    with pytest.raises(ValueError, match="omitted"):
        validate_decision_support_artifact(
            replace(artifact, contradictions=()),
            state=state,
            hypotheses=hypotheses,
            priority=priority,
            triage=triage,
        )


def test_ds_a_is_deterministic_across_repeated_packet_order() -> None:
    cases = _load()["cases"]
    assert isinstance(cases, list)
    baseline = {str(item["id"]): _products(item)[-1] for item in cases}
    for replay in range(8):
        ordered = cases if replay % 2 == 0 else tuple(reversed(cases))
        assert {str(item["id"]): _products(item)[-1] for item in ordered} == baseline


def test_ds_b_release_gate() -> None:
    fixture = json.loads(
        (FIXTURES / "scenario_cases.v1.json").read_text(encoding="utf-8")
    )
    assert fixture["fixture_version"] == "dm-ds-b-v1"
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases
    consistency_passed = 0
    policy_passed = 0
    policy_total = 0
    predictions: list[float] = []
    outcomes: list[int] = []

    for item in cases:
        state, hypotheses, _priority, triage, artifact = _products(item)
        analysis = artifact.scenario_analysis
        consistency_passed += analysis.mode == DecisionScenarioMode(
            str(item["expected_mode"])
        )
        assert analysis.recommendation.status == DecisionRecommendationStatus(
            str(item["expected_recommendation"])
        )
        assert analysis.assumption_sensitivity
        assert analysis.evidence_gaps == artifact.evidence_gaps
        material = next(
            scenario
            for scenario in analysis.scenarios
            if scenario.mode == DecisionScenarioMode.MATERIAL_HUMAN_IMPACT
        )
        variants = int(item["variants"])
        prediction_cycle = [material.probability] * variants
        predictions.extend(prediction_cycle)
        outcome_cycle = item.get("outcomes")
        if outcome_cycle is None:
            outcomes.extend([int(item["outcome"])] * variants)
        else:
            assert isinstance(outcome_cycle, list)
            outcomes.extend(
                int(outcome_cycle[index % len(outcome_cycle)])
                for index in range(variants)
            )
        constrained = (
            *artifact.options,
            *analysis.scenarios,
            analysis.recommendation,
        )
        for product in constrained:
            policy_total += 1
            constraints = getattr(
                product,
                "prohibited_actions",
                getattr(product, "policy_constraints", ()),
            )
            policy_passed += constraints == PROHIBITED_CONSEQUENTIAL_ACTIONS
        validate_scenario_analysis(
            analysis,
            state=state,
            facts=artifact.facts,
            assumptions=artifact.assumptions,
            options=artifact.options,
            hypotheses=hypotheses,
            triage=triage,
            expected_gaps=artifact.evidence_gaps,
        )

    consistency_rate = consistency_passed / len(cases)
    calibration_ece = expected_calibration_error(
        predictions, outcomes, bins=int(fixture["calibration_bins"])
    )
    policy_rate = policy_passed / policy_total
    assert consistency_rate >= 0.90, ("ds_b.scenario_consistency", consistency_rate)
    assert calibration_ece <= 0.05, ("ds_b.ece", calibration_ece)
    assert policy_rate >= 0.95, ("ds_b.policy_adherence", policy_rate)


def test_ds_b_disables_unsupported_recommendation_and_rejects_policy_escape() -> None:
    fixture = json.loads(
        (FIXTURES / "scenario_cases.v1.json").read_text(encoding="utf-8")
    )
    cases = fixture["cases"]
    assert isinstance(cases, list)
    missing = next(item for item in cases if item["id"] == "missing-neutral")
    state, hypotheses, _priority, triage, artifact = _products(missing)
    analysis = artifact.scenario_analysis
    recommendation = analysis.recommendation
    assert (
        recommendation.status
        == DecisionRecommendationStatus.DISABLED_UNSUPPORTED_PREMISE
    )
    assert recommendation.option_id is None
    assert recommendation.confidence is None
    assert recommendation.unsupported_premise_ids

    escaped = replace(analysis.scenarios[0], policy_constraints=("public_warning",))
    with pytest.raises(ValueError, match="policy lineage"):
        validate_scenario_analysis(
            replace(analysis, scenarios=(escaped, analysis.scenarios[1])),
            state=state,
            facts=artifact.facts,
            assumptions=artifact.assumptions,
            options=artifact.options,
            hypotheses=hypotheses,
            triage=triage,
            expected_gaps=artifact.evidence_gaps,
        )

    supported_case = next(
        item for item in cases if item["id"] == "explicit-zero-fatalities"
    )
    supported = _products(supported_case)[-1].scenario_analysis.recommendation
    assert supported.status == DecisionRecommendationStatus.AVAILABLE
    with pytest.raises(ValueError, match="unsupported premise"):
        replace(supported, unsupported_premise_ids=("premise:not-supported",))


def test_ds_c_release_gate() -> None:
    scenario_fixture = json.loads(
        (FIXTURES / "scenario_cases.v1.json").read_text(encoding="utf-8")
    )
    scenarios = {str(item["id"]): item for item in scenario_fixture["cases"]}
    fixture = json.loads(
        (FIXTURES / "autonomy_cases.v1.json").read_text(encoding="utf-8")
    )
    assert fixture["fixture_version"] == "dm-ds-c-v1"
    cases = fixture["cases"]
    assert isinstance(cases, list) and cases
    runs_per_case = int(fixture["runs_per_case"])
    pass_eight = 0
    correct_final_states = 0
    final_state_total = 0
    critical_policy_violations = 0
    controller = DecisionAutonomyController()

    for item in cases:
        scenario = scenarios[str(item["scenario_id"])]
        run_results: list[bool] = []
        expected_final = item["expected_final"]
        assert isinstance(expected_final, dict)
        for run in range(runs_per_case):
            variant = dict(scenario)
            reports = scenario.get("reports")
            if isinstance(reports, list) and run % 2:
                variant["reports"] = list(reversed(reports))
            artifact = _products(variant)[-1]
            requested = item.get("requested_action")
            outcome = controller.execute(
                artifact,
                requested_action=None if requested is None else str(requested),
            )
            final_snapshot = {
                "revision": outcome.final_state.revision,
                "monitoring": outcome.final_state.monitoring_active,
                "gap_priority": (outcome.final_state.evidence_gap_priority_active),
                "update_comparison": (
                    outcome.final_state.verified_update_comparison_active
                ),
            }
            final_correct = final_snapshot == expected_final
            result_correct = (
                outcome.autonomy_mode
                == DecisionAutonomyMode(str(item["expected_mode"]))
                and outcome.action
                == DecisionInternalAction(str(item["expected_action"]))
                and outcome.termination_reason == item["expected_termination"]
                and outcome.requires_human_intervention
                is bool(item["expected_requires_human"])
                and final_correct
            )
            correct_final_states += final_correct
            final_state_total += 1
            critical_policy_violations += any(
                (
                    outcome.final_state.public_warning_issued,
                    outcome.final_state.evacuation_directive_issued,
                    outcome.final_state.resource_allocation_ordered,
                )
            )
            validate_decision_execution(outcome, artifact)
            run_results.append(result_correct)
        pass_eight += all(run_results)

    pass_eight_rate = pass_eight / len(cases)
    final_state_rate = correct_final_states / final_state_total
    assert pass_eight_rate >= 0.95, ("ds_c.pass8", pass_eight_rate)
    assert final_state_rate >= 0.99, ("ds_c.final_state", final_state_rate)
    assert critical_policy_violations == 0, (
        "ds_c.critical_policy_violations",
        critical_policy_violations,
    )


def test_ds_c_rollback_and_authority_guards_preserve_state() -> None:
    scenario_fixture = json.loads(
        (FIXTURES / "scenario_cases.v1.json").read_text(encoding="utf-8")
    )
    cases = scenario_fixture["cases"]
    assert isinstance(cases, list)
    eligible = next(item for item in cases if item["id"] == "positive-injuries")
    artifact = _products(eligible)[-1]

    rollback = DecisionAutonomyController(autonomy_enabled=False).execute(artifact)
    assert rollback.autonomy_mode == DecisionAutonomyMode.ADVISORY_ONLY
    assert rollback.final_state == rollback.initial_state

    selected_id = artifact.scenario_analysis.recommendation.option_id
    tampered_options = tuple(
        replace(option, consequence=DecisionConsequence.HIGH)
        if option.option_id == selected_id
        else option
        for option in artifact.options
    )
    guarded = DecisionAutonomyController().execute(
        replace(artifact, options=tampered_options)
    )
    assert guarded.autonomy_mode == DecisionAutonomyMode.ADVISORY_ONLY
    assert guarded.termination_reason == "advisory_authority_guard_downgrade"
    assert guarded.final_state == guarded.initial_state

    with pytest.raises(ValueError, match="prohibited consequential effects"):
        DecisionExecutionState(
            artifact_id=artifact.artifact_id, public_warning_issued=True
        )
