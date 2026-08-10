import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from evidence_world_state_metrics import expected_calibration_error

from disaster_monitor.application.services.decision_support import (
    DecisionOptionGenerator,
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
    DecisionFact,
    DecisionRecommendationStatus,
    DecisionScenarioMode,
    DecisionStatementType,
)
from disaster_monitor.domain.disaster import (
    DisasterEvent,
    EvidenceDisposition,
    FactStatus,
    Hazard,
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
    hazard = Hazard(str(item["hazard"]))
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
        hazard=hazard,
        location=country.canonical_name,
        country=country,
        event_time=event_time,
        source=event_source,
        magnitude=(None if item.get("magnitude") is None else float(item["magnitude"])),
    )
    physical_event = (
        default_event_policy_registry()
        .for_hazard(hazard)
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
                hazard=hazard,
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
