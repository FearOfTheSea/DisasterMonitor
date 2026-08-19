"""Evidence-bounded analytical options over canonical EW and triage state."""

from hashlib import sha256

from disaster_monitor.application.services.scenario_reasoning import (
    DecisionScenarioSimulator,
    validate_scenario_analysis,
)
from disaster_monitor.domain.decision import (
    PROHIBITED_CONSEQUENTIAL_ACTIONS,
    DecisionAssumption,
    DecisionConsequence,
    DecisionContradiction,
    DecisionEstimate,
    DecisionFact,
    DecisionOption,
    DecisionSupportArtifact,
    decision_statement_type_for_source_status,
)
from disaster_monitor.domain.disaster import (
    EvidenceAvailability,
    EvidenceDisposition,
    EvidenceFreshness,
    EvidenceObservation,
    EvidenceWorldState,
    FactStatus,
    HypothesisArtifact,
    IncidentPriority,
    IncidentPriorityAssessment,
    InternalTriageDecision,
)

_IMPACT_CLAIMS = (
    "fatalities",
    "injuries",
    "missing",
    "evacuations",
    "physical_damage",
    "infrastructure",
)


class DecisionOptionGenerator:
    """Produce advisory analytical alternatives without adding facts or authority."""

    def generate(
        self,
        state: EvidenceWorldState,
        hypotheses: tuple[HypothesisArtifact, ...],
        priority: IncidentPriorityAssessment,
        triage: InternalTriageDecision,
    ) -> DecisionSupportArtifact:
        event = state.physical_event.event
        event_detail = (
            f"The selected source-backed {event.disaster.value} event occurred at "
            f"{event.location} at {event.event_time.isoformat()}."
        )
        if event.measurements:
            measurements = ", ".join(
                f"{item.kind.value} {item.value}"
                + (f" {item.unit}" if item.unit else "")
                for item in event.measurements
            )
            event_detail = f"{event_detail[:-1]} with {measurements}."
        facts: list[DecisionFact] = [
            DecisionFact(
                fact_id=_id("decision-fact", state.physical_event.physical_event_id),
                statement=event_detail,
                evidence_ids=(state.physical_event.physical_event_id,),
                source_ids=(event.source.source_id,),
                status="source_backed_event",
            )
        ]
        for observation in _decision_observations(state):
            fact = observation.fact
            facts.append(
                DecisionFact(
                    fact_id=_id("decision-fact", observation.observation_id),
                    statement=f"{fact.label}: {fact.value} ({fact.status.value}).",
                    evidence_ids=(observation.observation_id,),
                    source_ids=(fact.source.source_id,),
                    status=fact.status.value,
                    statement_type=decision_statement_type_for_source_status(
                        fact.status.value
                    ),
                )
            )

        estimates = tuple(
            DecisionEstimate(
                estimate_id=hypothesis.hypothesis_id,
                proposition=hypothesis.proposition,
                probability=hypothesis.probability,
                supporting_evidence_ids=hypothesis.supporting_evidence_ids,
                contradicting_evidence_ids=hypothesis.contradicting_evidence_ids,
                uncertain_evidence_ids=(hypothesis.uncertain_evidence_ids),
                rationale_rule_ids=tuple(
                    feature.rule_id for feature in hypothesis.rationale_features
                ),
            )
            for hypothesis in hypotheses
        )
        contradictions = _contradictions(state)
        evidence_gaps = _evidence_gaps(state)

        assumptions: list[DecisionAssumption] = [
            DecisionAssumption(
                assumption_id="assumption:approved-source-continuity",
                statement=(
                    "Only already approved, event-linked sources remain eligible for "
                    "follow-up information work."
                ),
                sensitivity="high",
                evidence_gap=(
                    "Future provider availability and update timing are not guaranteed."
                ),
            )
        ]
        if evidence_gaps:
            assumptions.append(
                DecisionAssumption(
                    assumption_id="assumption:evidence-incomplete",
                    statement=(
                        "The available packet may be incomplete; absent claims are "
                        "not treated as zero."
                    ),
                    sensitivity="high",
                    evidence_gap=" ".join(evidence_gaps),
                )
            )
        if contradictions:
            assumptions.append(
                DecisionAssumption(
                    assumption_id="assumption:conflict-unresolved",
                    statement=(
                        "Material source disagreement remains unresolved and no "
                        "single disputed value is assumed authoritative."
                    ),
                    sensitivity="high",
                    evidence_gap=(
                        "Conflicting observations require accountable review or a "
                        "later source correction."
                    ),
                )
            )

        event_fact_id = facts[0].fact_id
        options: list[DecisionOption] = [
            _option(
                state,
                "continue_approved_monitoring",
                "Continue approved-source monitoring",
                (
                    "Keep the existing internal monitoring path active and retrieve "
                    "only approved updates linked to this physical event."
                ),
                fact_ids=(event_fact_id,),
                assumption_ids=("assumption:approved-source-continuity",),
                trade_offs=(
                    "May not resolve urgent evidence gaps immediately.",
                    "Avoids unsupported substitution and preserves provenance.",
                ),
                uncertainties=(
                    "Provider timing and future availability remain unknown.",
                ),
                consequence=DecisionConsequence.LOW,
                requires_human_approval=False,
            )
        ]
        if evidence_gaps:
            options.append(
                _option(
                    state,
                    "prioritize_evidence_gaps",
                    "Prioritize unresolved evidence gaps",
                    (
                        "Place the missing or stale information needs ahead of routine "
                        "internal follow-up while retaining the current priority."
                    ),
                    fact_ids=(event_fact_id,),
                    assumption_ids=("assumption:evidence-incomplete",),
                    trade_offs=(
                        "Uses analyst attention that could cover other incidents.",
                        "Reduces the chance that missing evidence is mistaken for "
                        "safety.",
                    ),
                    uncertainties=tuple(evidence_gaps),
                    consequence=DecisionConsequence.MODERATE,
                    requires_human_approval=False,
                )
            )
        if contradictions:
            options.append(
                _option(
                    state,
                    "review_material_conflicts",
                    "Review material evidence conflicts",
                    (
                        "Present every conflicting observation and its lineage to an "
                        "accountable human without selecting a convenient value."
                    ),
                    fact_ids=tuple(fact.fact_id for fact in facts),
                    assumption_ids=("assumption:conflict-unresolved",),
                    trade_offs=(
                        "Human review may delay a consolidated internal picture.",
                        "Preserves material disagreement and avoids false certainty.",
                    ),
                    uncertainties=tuple(item.detail for item in contradictions),
                    consequence=DecisionConsequence.HIGH,
                    requires_human_approval=True,
                )
            )
        if priority.priority in {IncidentPriority.HIGH, IncidentPriority.CRITICAL} or (
            triage.requires_human_intervention
        ):
            options.append(
                _option(
                    state,
                    "route_accountable_review",
                    "Route the evidence packet to accountable review",
                    (
                        "Keep the incident visible and send the evidence, priority "
                        "signals, gaps, and contradictions to a human decision-maker."
                    ),
                    fact_ids=tuple(fact.fact_id for fact in facts),
                    estimate_ids=tuple(item.estimate_id for item in estimates),
                    assumption_ids=tuple(item.assumption_id for item in assumptions),
                    trade_offs=(
                        "Requires human attention before closure.",
                        "Prevents analytical priority from becoming operational "
                        "authority.",
                    ),
                    uncertainties=(
                        "The accountable human may require additional evidence.",
                    ),
                    consequence=DecisionConsequence.HIGH,
                    requires_human_approval=True,
                )
            )
        if any(
            claim.claim_key in _IMPACT_CLAIMS and claim.current is not None
            for claim in state.claims
        ):
            options.append(
                _option(
                    state,
                    "compare_verified_updates",
                    "Compare verified impact updates",
                    (
                        "Maintain an internal comparison of current, superseded, and "
                        "conflicting impact observations before revising the picture."
                    ),
                    fact_ids=tuple(fact.fact_id for fact in facts[1:]),
                    assumption_ids=("assumption:approved-source-continuity",),
                    trade_offs=(
                        "Adds review work when source updates are frequent.",
                        "Makes changes and retained history auditable.",
                    ),
                    uncertainties=(
                        "Later official updates may supersede current observations.",
                    ),
                    consequence=DecisionConsequence.MODERATE,
                    requires_human_approval=False,
                )
            )

        scenario_analysis = DecisionScenarioSimulator().simulate(
            state,
            hypotheses,
            tuple(facts),
            tuple(assumptions),
            tuple(options),
            evidence_gaps,
            triage,
        )
        material = "|".join(
            (
                state.state_version,
                priority.assessment_id,
                triage.decision_id,
                *(option.option_id for option in options),
            )
        )
        artifact = DecisionSupportArtifact(
            artifact_id=_id("decision-support", material),
            physical_event_id=state.physical_event.physical_event_id,
            evidence_state_version=state.state_version,
            priority_assessment_id=priority.assessment_id,
            triage_decision_id=triage.decision_id,
            facts=tuple(facts),
            estimates=estimates,
            assumptions=tuple(assumptions),
            options=tuple(options),
            contradictions=contradictions,
            evidence_gaps=evidence_gaps,
            scenario_analysis=scenario_analysis,
            generated_at=state.evaluated_at,
        )
        validate_decision_support_artifact(
            artifact,
            state=state,
            hypotheses=hypotheses,
            priority=priority,
            triage=triage,
        )
        return artifact


def validate_decision_support_artifact(
    artifact: DecisionSupportArtifact,
    *,
    state: EvidenceWorldState,
    hypotheses: tuple[HypothesisArtifact, ...],
    priority: IncidentPriorityAssessment,
    triage: InternalTriageDecision,
) -> None:
    if (
        artifact.physical_event_id != state.physical_event.physical_event_id
        or artifact.evidence_state_version != state.state_version
        or artifact.priority_assessment_id != priority.assessment_id
        or artifact.triage_decision_id != triage.decision_id
    ):
        raise ValueError("Decision support escaped canonical state lineage.")
    known_evidence_ids = {
        state.physical_event.physical_event_id,
        *(
            item.observation.observation_id
            for claim in state.claims
            for item in claim.history
        ),
    }
    known_source_ids = {
        state.physical_event.event.source.source_id,
        *(
            item.observation.fact.source.source_id
            for claim in state.claims
            for item in claim.history
        ),
    }
    if any(
        not set(fact.evidence_ids) <= known_evidence_ids
        or not set(fact.source_ids) <= known_source_ids
        for fact in artifact.facts
    ):
        raise ValueError("Decision fact lacks canonical evidence/source support.")
    expected_observations = {
        observation.observation_id: observation
        for observation in _decision_observations(state)
    }
    source_facts = tuple(
        fact
        for fact in artifact.facts
        if state.physical_event.physical_event_id not in fact.evidence_ids
    )
    if len(artifact.facts) != len(source_facts) + 1 or {
        evidence_id for fact in source_facts for evidence_id in fact.evidence_ids
    } != set(expected_observations):
        raise ValueError("Decision support omitted an eligible source observation.")
    for fact in source_facts:
        if len(fact.evidence_ids) != 1:
            raise ValueError("Decision fact source status escaped observation lineage.")
        observation = expected_observations[fact.evidence_ids[0]]
        expected_status = observation.fact.status.value
        if (
            fact.status != expected_status
            or fact.source_ids != (observation.fact.source.source_id,)
            or fact.statement_type
            != decision_statement_type_for_source_status(expected_status)
        ):
            raise ValueError("Decision fact source status was promoted or changed.")
    hypothesis_by_id = {item.hypothesis_id: item for item in hypotheses}
    if any(
        estimate.estimate_id not in hypothesis_by_id
        or not set(
            (
                *estimate.supporting_evidence_ids,
                *estimate.contradicting_evidence_ids,
                *estimate.uncertain_evidence_ids,
            )
        )
        <= known_evidence_ids
        or estimate.supporting_evidence_ids
        != hypothesis_by_id[estimate.estimate_id].supporting_evidence_ids
        or estimate.contradicting_evidence_ids
        != hypothesis_by_id[estimate.estimate_id].contradicting_evidence_ids
        or estimate.uncertain_evidence_ids
        != hypothesis_by_id[estimate.estimate_id].uncertain_evidence_ids
        or estimate.rationale_rule_ids
        != tuple(
            feature.rule_id
            for feature in hypothesis_by_id[estimate.estimate_id].rationale_features
        )
        for estimate in artifact.estimates
    ):
        raise ValueError("Decision estimate escaped typed hypothesis lineage.")
    fact_ids = {item.fact_id for item in artifact.facts}
    estimate_ids = {item.estimate_id for item in artifact.estimates}
    assumption_ids = {item.assumption_id for item in artifact.assumptions}
    if any(
        not set(option.supporting_fact_ids) <= fact_ids
        or not set(option.supporting_estimate_ids) <= estimate_ids
        or not set(option.assumption_ids) <= assumption_ids
        or option.prohibited_actions != PROHIBITED_CONSEQUENTIAL_ACTIONS
        for option in artifact.options
    ):
        raise ValueError(
            "Decision option lacks traceable inputs or policy constraints."
        )
    expected_conflicts = {
        claim.claim_key
        for claim in state.claims
        if any(
            item.disposition == EvidenceDisposition.CONFLICTING
            for item in claim.history
        )
    }
    if {item.claim_key for item in artifact.contradictions} != expected_conflicts:
        raise ValueError("Decision support omitted a material evidence contradiction.")
    validate_scenario_analysis(
        artifact.scenario_analysis,
        state=state,
        facts=artifact.facts,
        assumptions=artifact.assumptions,
        options=artifact.options,
        hypotheses=hypotheses,
        triage=triage,
        expected_gaps=artifact.evidence_gaps,
    )


def render_decision_support(artifact: DecisionSupportArtifact) -> str:
    lines = [
        "Advisory analytical options only; these are not official orders or directives."
    ]
    lines.extend(
        f"- Source evidence [{fact.statement_type.value}; status={fact.status}]: "
        f"{fact.statement}"
        for fact in artifact.facts
    )
    lines.extend(
        f"- DM analytical estimate [{estimate.statement_type.value}; inferred]: "
        f"{estimate.proposition} Probability {estimate.probability:.2f}."
        for estimate in artifact.estimates
    )
    for option in artifact.options:
        approval = (
            " Human approval is required."
            if option.requires_human_approval
            else " The option is limited to reversible internal information work."
        )
        lines.append(
            f"- {option.title}: {option.description}{approval} "
            f"Trade-offs: {'; '.join(option.trade_offs)} "
            f"Uncertainty: {'; '.join(option.uncertainties)}"
        )
    if artifact.contradictions:
        lines.append(
            "- Material contradictions retained: "
            + "; ".join(item.detail for item in artifact.contradictions)
        )
    analysis = artifact.scenario_analysis
    lines.append(
        "- Scenario mode: "
        f"{analysis.mode.value}. Sensitivity: "
        + "; ".join(analysis.assumption_sensitivity)
    )
    if analysis.evidence_gaps:
        lines.append("- Evidence gaps: " + "; ".join(analysis.evidence_gaps))
    recommendation = analysis.recommendation
    lines.append(
        f"- Recommendation layer ({recommendation.status.value}): "
        f"{recommendation.rationale}"
    )
    return "\n".join(lines)


def _contradictions(
    state: EvidenceWorldState,
) -> tuple[DecisionContradiction, ...]:
    results: list[DecisionContradiction] = []
    for claim in state.claims:
        conflicting = tuple(
            item.observation.observation_id
            for item in claim.history
            if item.disposition == EvidenceDisposition.CONFLICTING
        )
        if not conflicting:
            continue
        current = () if claim.current is None else (claim.current.observation_id,)
        evidence_ids = tuple(dict.fromkeys((*current, *conflicting)))
        results.append(
            DecisionContradiction(
                contradiction_id=_id("decision-conflict", *evidence_ids),
                claim_key=claim.claim_key,
                evidence_ids=evidence_ids,
                detail=(
                    f"Claim {claim.claim_key} retains {len(evidence_ids)} materially "
                    "different current observations."
                ),
            )
        )
    return tuple(results)


def _evidence_gaps(state: EvidenceWorldState) -> tuple[str, ...]:
    gaps: list[str] = []
    for claim_key in _IMPACT_CLAIMS:
        claim = state.claim(claim_key)
        if claim.availability == EvidenceAvailability.ABSENT:
            gaps.append(f"No current usable source observation for {claim_key}.")
        elif (
            claim.current is not None
            and claim.current.fact.status != FactStatus.CONFIRMED
        ):
            gaps.append(
                f"Current {claim_key} observation is "
                f"{claim.current.fact.status.value}, not confirmed."
            )
    stale = [
        claim.claim_key
        for claim in state.claims
        if claim.current is not None
        and any(
            item.observation == claim.current
            and item.freshness == EvidenceFreshness.STALE
            for item in claim.history
        )
    ]
    gaps.extend(f"Current {claim_key} evidence is stale." for claim_key in stale)
    return tuple(gaps)


def _decision_observations(
    state: EvidenceWorldState,
) -> tuple[EvidenceObservation, ...]:
    observations = (
        item.observation
        for claim in state.claims
        for item in claim.history
        if item.disposition
        in {EvidenceDisposition.CURRENT, EvidenceDisposition.CONFLICTING}
    )
    return tuple(
        sorted(
            observations,
            key=lambda item: (
                item.claim_key,
                item != state.claim(item.claim_key).current,
                item.observation_id,
            ),
        )
    )


def _option(
    state: EvidenceWorldState,
    kind: str,
    title: str,
    description: str,
    *,
    fact_ids: tuple[str, ...] = (),
    estimate_ids: tuple[str, ...] = (),
    assumption_ids: tuple[str, ...] = (),
    trade_offs: tuple[str, ...],
    uncertainties: tuple[str, ...],
    consequence: DecisionConsequence,
    requires_human_approval: bool,
) -> DecisionOption:
    return DecisionOption(
        option_id=_id("decision-option", state.state_version, kind),
        option_kind=kind,
        title=title,
        description=description,
        supporting_fact_ids=fact_ids,
        supporting_estimate_ids=estimate_ids,
        assumption_ids=assumption_ids,
        trade_offs=trade_offs,
        uncertainties=uncertainties,
        consequence=consequence,
        reversible=True,
        requires_human_approval=requires_human_approval,
        prohibited_actions=PROHIBITED_CONSEQUENTIAL_ACTIONS,
    )


def _id(prefix: str, *values: str) -> str:
    material = "|".join(values)
    return f"{prefix}:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
