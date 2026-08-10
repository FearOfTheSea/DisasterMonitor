"""Calibrated counterfactual scenarios and fail-closed recommendations."""

from hashlib import sha256

from disaster_monitor.domain.decision import (
    PROHIBITED_CONSEQUENTIAL_ACTIONS,
    DecisionAssumption,
    DecisionConsequence,
    DecisionFact,
    DecisionOption,
    DecisionRecommendation,
    DecisionRecommendationStatus,
    DecisionScenario,
    DecisionScenarioAnalysis,
    DecisionScenarioMode,
)
from disaster_monitor.domain.disaster import (
    EvidenceWorldState,
    HypothesisArtifact,
    InternalTriageDecision,
)


class DecisionScenarioSimulator:
    """Project paired analytical scenarios without inventing evidence or authority."""

    def simulate(
        self,
        state: EvidenceWorldState,
        hypotheses: tuple[HypothesisArtifact, ...],
        facts: tuple[DecisionFact, ...],
        assumptions: tuple[DecisionAssumption, ...],
        options: tuple[DecisionOption, ...],
        evidence_gaps: tuple[str, ...],
        triage: InternalTriageDecision,
    ) -> DecisionScenarioAnalysis:
        if not hypotheses:
            raise ValueError("Scenario reasoning requires a typed calibrated estimate.")
        estimate = hypotheses[0]
        sensitivity = _sensitivity(evidence_gaps, estimate)
        assumption_ids = tuple(item.assumption_id for item in assumptions)
        material_fact_ids = _fact_ids_for_evidence(
            facts, estimate.supporting_evidence_ids
        )
        limited_fact_ids = _fact_ids_for_evidence(
            facts, estimate.contradicting_evidence_ids
        )
        scenarios = (
            DecisionScenario(
                scenario_id=_id(
                    "decision-scenario",
                    state.state_version,
                    DecisionScenarioMode.MATERIAL_HUMAN_IMPACT.value,
                ),
                mode=DecisionScenarioMode.MATERIAL_HUMAN_IMPACT,
                title="Material human impact in current evidence",
                description=(
                    "Treat the calibrated human-impact estimate as the material "
                    "branch while retaining every supporting and conflicting record."
                ),
                probability=estimate.probability,
                supporting_fact_ids=material_fact_ids,
                supporting_estimate_ids=(estimate.hypothesis_id,),
                assumption_ids=assumption_ids,
                trade_offs=(
                    "Earlier accountable review may consume scarce analyst attention.",
                    "It reduces delay when verified human-impact evidence is positive.",
                ),
                sensitivity=sensitivity,
                evidence_gaps=evidence_gaps,
                policy_constraints=PROHIBITED_CONSEQUENTIAL_ACTIONS,
            ),
            DecisionScenario(
                scenario_id=_id(
                    "decision-scenario",
                    state.state_version,
                    DecisionScenarioMode.LIMITED_OBSERVED_HUMAN_IMPACT.value,
                ),
                mode=DecisionScenarioMode.LIMITED_OBSERVED_HUMAN_IMPACT,
                title="Limited human impact in currently observed evidence",
                description=(
                    "Treat explicit current zero evidence as the limited-observation "
                    "branch without converting missing evidence into safety."
                ),
                probability=1 - estimate.probability,
                supporting_fact_ids=limited_fact_ids,
                supporting_estimate_ids=(estimate.hypothesis_id,),
                assumption_ids=assumption_ids,
                trade_offs=(
                    "Routine monitoring preserves capacity for other incidents.",
                    "A late or incomplete source update can change this branch.",
                ),
                sensitivity=sensitivity,
                evidence_gaps=evidence_gaps,
                policy_constraints=PROHIBITED_CONSEQUENTIAL_ACTIONS,
            ),
        )
        mode = _mode(estimate.probability)
        recommendation = _recommendation(
            mode=mode,
            estimate=estimate,
            material_fact_ids=material_fact_ids,
            limited_fact_ids=limited_fact_ids,
            assumptions=assumptions,
            options=options,
            sensitivity=sensitivity,
            evidence_gaps=evidence_gaps,
            triage=triage,
        )
        analysis = DecisionScenarioAnalysis(
            analysis_id=_id(
                "decision-scenario-analysis",
                state.state_version,
                estimate.hypothesis_id,
            ),
            evidence_state_version=state.state_version,
            scenarios=scenarios,
            mode=mode,
            assumption_sensitivity=sensitivity,
            evidence_gaps=evidence_gaps,
            recommendation=recommendation,
        )
        validate_scenario_analysis(
            analysis,
            state=state,
            facts=facts,
            assumptions=assumptions,
            options=options,
            hypotheses=hypotheses,
            triage=triage,
            expected_gaps=evidence_gaps,
        )
        return analysis


def validate_scenario_analysis(
    analysis: DecisionScenarioAnalysis,
    *,
    state: EvidenceWorldState,
    facts: tuple[DecisionFact, ...],
    assumptions: tuple[DecisionAssumption, ...],
    options: tuple[DecisionOption, ...],
    hypotheses: tuple[HypothesisArtifact, ...],
    triage: InternalTriageDecision,
    expected_gaps: tuple[str, ...],
) -> None:
    if analysis.evidence_state_version != state.state_version:
        raise ValueError("Scenario analysis escaped canonical evidence state.")
    fact_ids = {item.fact_id for item in facts}
    assumption_ids = {item.assumption_id for item in assumptions}
    estimate_ids = {item.hypothesis_id for item in hypotheses}
    if any(
        not set(scenario.supporting_fact_ids) <= fact_ids
        or not set(scenario.supporting_estimate_ids) <= estimate_ids
        or not set(scenario.assumption_ids) <= assumption_ids
        or scenario.policy_constraints != PROHIBITED_CONSEQUENTIAL_ACTIONS
        or scenario.evidence_gaps != expected_gaps
        for scenario in analysis.scenarios
    ):
        raise ValueError("Scenario escaped evidence, assumption, or policy lineage.")
    scenarios_by_mode = {item.mode: item for item in analysis.scenarios}
    if set(scenarios_by_mode) != {
        DecisionScenarioMode.MATERIAL_HUMAN_IMPACT,
        DecisionScenarioMode.LIMITED_OBSERVED_HUMAN_IMPACT,
    }:
        raise ValueError("Scenario analysis requires both declared counterfactuals.")
    material_probability = scenarios_by_mode[
        DecisionScenarioMode.MATERIAL_HUMAN_IMPACT
    ].probability
    limited_probability = scenarios_by_mode[
        DecisionScenarioMode.LIMITED_OBSERVED_HUMAN_IMPACT
    ].probability
    if abs(material_probability + limited_probability - 1) > 1e-9:
        raise ValueError("Counterfactual scenario probabilities must sum to one.")
    if analysis.mode != _mode(material_probability):
        raise ValueError("Scenario mode is inconsistent with calibrated probabilities.")
    if analysis.evidence_gaps != expected_gaps:
        raise ValueError("Scenario analysis omitted an evidence gap.")

    recommendation = analysis.recommendation
    option_by_id = {item.option_id: item for item in options}
    if (
        recommendation.policy_constraints != PROHIBITED_CONSEQUENTIAL_ACTIONS
        or not set(recommendation.premise_fact_ids) <= fact_ids
        or not set(recommendation.premise_estimate_ids) <= estimate_ids
    ):
        raise ValueError("Recommendation escaped evidence or policy constraints.")
    if recommendation.status == DecisionRecommendationStatus.AVAILABLE:
        option = (
            None
            if recommendation.option_id is None
            else option_by_id.get(recommendation.option_id)
        )
        if (
            option is None
            or not option.reversible
            or option.consequence == DecisionConsequence.HIGH
            or option.requires_human_approval
            or recommendation.unsupported_premise_ids
            or analysis.mode == DecisionScenarioMode.UNRESOLVED
            or triage.requires_human_intervention
        ):
            raise ValueError(
                "Recommendation depends on unsupported premise or ineligible authority."
            )
    elif recommendation.option_id is not None:
        raise ValueError("Disabled recommendation selected an option.")
    if (
        analysis.mode == DecisionScenarioMode.UNRESOLVED
        and recommendation.status
        not in {
            DecisionRecommendationStatus.DISABLED_UNSUPPORTED_PREMISE,
            DecisionRecommendationStatus.HUMAN_REVIEW_REQUIRED,
        }
    ):
        raise ValueError("Unresolved scenario did not disable recommendation output.")


def _recommendation(
    *,
    mode: DecisionScenarioMode,
    estimate: HypothesisArtifact,
    material_fact_ids: tuple[str, ...],
    limited_fact_ids: tuple[str, ...],
    assumptions: tuple[DecisionAssumption, ...],
    options: tuple[DecisionOption, ...],
    sensitivity: tuple[str, ...],
    evidence_gaps: tuple[str, ...],
    triage: InternalTriageDecision,
) -> DecisionRecommendation:
    if triage.requires_human_intervention:
        return DecisionRecommendation(
            status=DecisionRecommendationStatus.HUMAN_REVIEW_REQUIRED,
            option_id=None,
            confidence=None,
            premise_fact_ids=(),
            premise_estimate_ids=(estimate.hypothesis_id,),
            unsupported_premise_ids=(),
            rationale=(
                "The verified priority or uncertainty state requires accountable "
                "human review; no recommendation is selected."
            ),
            sensitivity=sensitivity,
            evidence_gaps=evidence_gaps,
            policy_constraints=PROHIBITED_CONSEQUENTIAL_ACTIONS,
        )
    branch_fact_ids = (
        material_fact_ids
        if mode == DecisionScenarioMode.MATERIAL_HUMAN_IMPACT
        else limited_fact_ids
    )
    if mode == DecisionScenarioMode.UNRESOLVED or not branch_fact_ids:
        unsupported = tuple(
            item.assumption_id
            for item in assumptions
            if item.assumption_id != "assumption:approved-source-continuity"
        ) or ("premise:human-impact-unresolved",)
        return DecisionRecommendation(
            status=DecisionRecommendationStatus.DISABLED_UNSUPPORTED_PREMISE,
            option_id=None,
            confidence=None,
            premise_fact_ids=(),
            premise_estimate_ids=(estimate.hypothesis_id,),
            unsupported_premise_ids=unsupported,
            rationale=(
                "No high-confidence option is selected because the leading scenario "
                "depends on an unresolved or unsupported premise."
            ),
            sensitivity=sensitivity,
            evidence_gaps=evidence_gaps,
            policy_constraints=PROHIBITED_CONSEQUENTIAL_ACTIONS,
        )
    selected_kind = (
        "compare_verified_updates"
        if mode == DecisionScenarioMode.MATERIAL_HUMAN_IMPACT
        else "continue_approved_monitoring"
    )
    selected_option = next(
        item for item in options if item.option_kind == selected_kind
    )
    confidence = (
        estimate.probability
        if mode == DecisionScenarioMode.MATERIAL_HUMAN_IMPACT
        else 1 - estimate.probability
    )
    return DecisionRecommendation(
        status=DecisionRecommendationStatus.AVAILABLE,
        option_id=selected_option.option_id,
        confidence=confidence,
        premise_fact_ids=branch_fact_ids,
        premise_estimate_ids=(estimate.hypothesis_id,),
        unsupported_premise_ids=(),
        rationale=(
            f"Select the reversible internal {selected_kind} option; this does not "
            "authorize any public or operational action."
        ),
        sensitivity=sensitivity,
        evidence_gaps=evidence_gaps,
        policy_constraints=PROHIBITED_CONSEQUENTIAL_ACTIONS,
    )


def _mode(probability: float) -> DecisionScenarioMode:
    if probability >= 0.75:
        return DecisionScenarioMode.MATERIAL_HUMAN_IMPACT
    if probability <= 0.25:
        return DecisionScenarioMode.LIMITED_OBSERVED_HUMAN_IMPACT
    return DecisionScenarioMode.UNRESOLVED


def _fact_ids_for_evidence(
    facts: tuple[DecisionFact, ...], evidence_ids: tuple[str, ...]
) -> tuple[str, ...]:
    evidence = set(evidence_ids)
    return tuple(
        item.fact_id for item in facts if evidence.intersection(item.evidence_ids)
    )


def _sensitivity(
    evidence_gaps: tuple[str, ...], estimate: HypothesisArtifact
) -> tuple[str, ...]:
    lines = [
        "A verified correction to current human-impact evidence requires scenario "
        "recalculation."
    ]
    if evidence_gaps:
        lines.append(
            "Filling a listed missing or stale evidence gap may change the leading "
            "scenario."
        )
    if estimate.supporting_evidence_ids and estimate.contradicting_evidence_ids:
        lines.append(
            "Resolving the retained material conflict may move probability away "
            "from the neutral branch."
        )
    return tuple(lines)


def _id(prefix: str, *values: str) -> str:
    material = "|".join(values)
    return f"{prefix}:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
