"""Evidence-state-owned incident priority policy for internal attention routing."""

import re
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from disaster_monitor.domain.disaster import (
    ClaimEvidenceState,
    EvidenceAvailability,
    EvidenceDisposition,
    EvidenceFreshness,
    EvidenceWorldState,
    Hazard,
    IncidentPriority,
    IncidentPriorityAssessment,
    IncidentPrioritySignal,
)

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
_ACTIVE_WARNING = re.compile(
    r"\b(?:active|issued|warning|watch|advisory|evacuate|evacuation)\b", re.I
)
_NEGATED_WARNING = re.compile(
    r"\b(?:no|none|cancelled|canceled|expired|lifted|not expected)\b", re.I
)
_SEVERE_DAMAGE = re.compile(
    r"\b(?:major|severe|widespread|destroyed|collapsed|uninhabitable)\b", re.I
)
_CLAUSE_BOUNDARY = re.compile(
    r"\s*(?:[.;]|\bbut\b|\bhowever\b|\balthough\b|\bthough\b|\bwhile\b|"
    r"\bdespite\b)\s*",
    re.I,
)
_EXPLICIT_NO_OPERATIONAL_IMPACT = re.compile(
    r"\bnone\b|\b(?:no|without)\s+"
    r"(?:reported\s+|material\s+|significant\s+)?"
    r"(?:operational\s+)?(?:disruption|impact|damage|outage|closure)s?\b|"
    r"\b(?:remain(?:s|ed)?|is|are|was|were)\s+(?:fully\s+)?operational\b|"
    r"\b(?:unaffected|undamaged|fully\s+available|normal\s+operations?)\b|"
    r"\bnot\s+(?:inoperable|unavailable|disrupted|closed|offline)\b|"
    r"\bnot\s+(?:true|the\s+case)\s+that\b[^.;]{0,80}"
    r"\bnot\s+(?:fully\s+)?operational\b",
    re.I,
)
_OPERATIONAL_IMPACT = re.compile(
    r"\b(?:operational\s+)?disrupt(?:ed|ion|ions|ive)?\b|"
    r"\b(?:outage|outages|closure|closures|closed|blocked|inaccessible|"
    r"unavailable|offline|failure|failures|failed|damage|damaged|destroyed|"
    r"collapsed)\b|"
    r"\b(?:severely\s+)?reduced\s+(?:service|services|capacity|access)\b|"
    r"\b(?:partial|partially|partly|limited)\s+"
    r"(?:availability|available|capacity|operations?|operational)\b|"
    r"\bnot\s+(?:fully\s+)?operational\b",
    re.I,
)
_AMBIGUOUS_OPERATIONAL_IMPACT = re.compile(
    r"\b(?:not\s+(?:unaffected|undamaged)|not\s+ruled\s+out|"
    r"(?:cannot|could\s+not)\s+be\s+ruled\s+out|unclear|uncertain|unconfirmed|"
    r"status\s+(?:is\s+)?pending)\b",
    re.I,
)
_IRRELEVANT_OPERATIONAL_CONTEXT = re.compile(
    r"\boperational\s+(?:team|teams|briefing|plan|planning|exercise|"
    r"assessment|review|response)\b",
    re.I,
)

_PRIORITY_ORDER = {
    IncidentPriority.LOW: 0,
    IncidentPriority.MODERATE: 1,
    IncidentPriority.HIGH: 2,
    IncidentPriority.CRITICAL: 3,
}


class _ImpactInterpretation(StrEnum):
    NO_IMPACT = "no_impact"
    IMPACT = "impact"
    AMBIGUOUS = "ambiguous"


class _SignalAdder(Protocol):
    def __call__(
        self,
        rule_id: str,
        detail: str,
        score_delta: int,
        *,
        evidence_ids: tuple[str, ...] = (),
        priority_floor: IncidentPriority = IncidentPriority.LOW,
    ) -> None: ...


class IncidentPriorityRanker:
    """Rank incidents without source access, model inference, or country weighting."""

    def assess(self, state: EvidenceWorldState) -> IncidentPriorityAssessment:
        event = state.physical_event.event
        signals: list[IncidentPrioritySignal] = []
        floor = IncidentPriority.LOW
        uncertainty_escalated = False

        def add(
            rule_id: str,
            detail: str,
            score_delta: int,
            *,
            evidence_ids: tuple[str, ...] = (),
            priority_floor: IncidentPriority = IncidentPriority.LOW,
        ) -> None:
            nonlocal floor
            signals.append(
                IncidentPrioritySignal(
                    rule_id=rule_id,
                    detail=detail,
                    score_delta=score_delta,
                    evidence_ids=evidence_ids,
                )
            )
            floor = _max_priority(floor, priority_floor)

        if event.hazard == Hazard.EARTHQUAKE and event.magnitude is not None:
            if event.magnitude >= 7:
                add(
                    "tr.priority.earthquake_magnitude_critical",
                    "Verified earthquake magnitude is at least 7.0.",
                    55,
                    priority_floor=IncidentPriority.CRITICAL,
                )
            elif event.magnitude >= 6:
                add(
                    "tr.priority.earthquake_magnitude_high",
                    "Verified earthquake magnitude is at least 6.0.",
                    38,
                    priority_floor=IncidentPriority.HIGH,
                )
            elif event.magnitude >= 5:
                add(
                    "tr.priority.earthquake_magnitude_moderate",
                    "Verified earthquake magnitude is at least 5.0.",
                    22,
                    priority_floor=IncidentPriority.MODERATE,
                )
            elif event.magnitude >= 4:
                add(
                    "tr.priority.earthquake_magnitude_observed",
                    "Verified earthquake magnitude is at least 4.0.",
                    10,
                )

        intensity = _intensity_level(event.intensity)
        if intensity is not None and intensity >= 7:
            add(
                "tr.priority.intensity_critical",
                "Verified event intensity reached the declared critical level.",
                55,
                priority_floor=IncidentPriority.CRITICAL,
            )
        elif intensity is not None and intensity >= 6:
            add(
                "tr.priority.intensity_high",
                "Verified event intensity reached the declared high level.",
                40,
                priority_floor=IncidentPriority.HIGH,
            )

        if event.significance is not None:
            if event.significance >= 1_000:
                add(
                    "tr.priority.provider_significance_critical",
                    "Verified provider significance is at least 1000.",
                    50,
                    priority_floor=IncidentPriority.CRITICAL,
                )
            elif event.significance >= 600:
                add(
                    "tr.priority.provider_significance_high",
                    "Verified provider significance is at least 600.",
                    35,
                    priority_floor=IncidentPriority.HIGH,
                )
            elif event.significance >= 300:
                add(
                    "tr.priority.provider_significance_moderate",
                    "Verified provider significance is at least 300.",
                    20,
                    priority_floor=IncidentPriority.MODERATE,
                )

        self._add_human_impact_signals(state, add)
        if self._add_operational_signals(state, add):
            uncertainty_escalated = True

        conflicting_ids = tuple(
            sorted(
                item.observation.observation_id
                for claim in state.claims
                for item in claim.history
                if item.disposition == EvidenceDisposition.CONFLICTING
            )
        )
        if conflicting_ids:
            uncertainty_escalated = True
            add(
                "tr.priority.material_conflict_escalation",
                "Materially conflicting current evidence raises review priority.",
                15,
                evidence_ids=conflicting_ids,
                priority_floor=IncidentPriority.HIGH,
            )

        stale_ids = tuple(
            sorted(
                claim.current.observation_id
                for claim in state.claims
                if claim.current is not None
                and any(
                    item.observation == claim.current
                    and item.freshness == EvidenceFreshness.STALE
                    for item in claim.history
                )
            )
        )
        if stale_ids:
            uncertainty_escalated = True
            add(
                "tr.priority.stale_current_evidence_escalation",
                "Stale current evidence raises review priority.",
                10,
                evidence_ids=stale_ids,
                priority_floor=IncidentPriority.MODERATE,
            )

        ambiguous = tuple(
            item.observation_key
            for item in state.physical_event.assignments
            if item.status.value == "ambiguous"
        )
        if ambiguous:
            uncertainty_escalated = True
            add(
                "tr.priority.ambiguous_event_escalation",
                "Ambiguous physical-event assignment raises review priority.",
                20,
                priority_floor=IncidentPriority.HIGH,
            )

        score_before_gap = sum(item.score_delta for item in signals)
        human_impact_present = any(
            state.claim(key).availability == EvidenceAvailability.PRESENT
            for key in ("fatalities", "injuries", "missing")
        )
        if score_before_gap >= 20 and not human_impact_present:
            uncertainty_escalated = True
            add(
                "tr.priority.unresolved_human_impact_gap",
                "A material event lacks current human-impact evidence; uncertainty "
                "raises rather than lowers priority.",
                15,
                priority_floor=IncidentPriority.MODERATE,
            )

        score = min(100, sum(item.score_delta for item in signals))
        priority = _max_priority(_score_priority(score), floor)
        assessment_material = "|".join(
            (
                state.physical_event.physical_event_id,
                state.state_version,
                priority.value,
                str(score),
                *(item.rule_id for item in signals),
            )
        )
        assessment_id = (
            f"priority:{sha256(assessment_material.encode('utf-8')).hexdigest()[:24]}"
        )
        return IncidentPriorityAssessment(
            assessment_id=assessment_id,
            physical_event_id=state.physical_event.physical_event_id,
            evidence_state_version=state.state_version,
            priority=priority,
            score=score,
            requires_human_review=(
                priority == IncidentPriority.CRITICAL or uncertainty_escalated
            ),
            uncertainty_escalated=uncertainty_escalated,
            signals=tuple(signals),
            assessed_at=state.evaluated_at,
        )

    def rank(
        self, states: tuple[EvidenceWorldState, ...]
    ) -> tuple[IncidentPriorityAssessment, ...]:
        assessed_states = tuple((self.assess(state), state) for state in states)
        return tuple(
            assessment
            for assessment, _state in sorted(
                assessed_states,
                key=lambda item: (
                    -_PRIORITY_ORDER[item[0].priority],
                    -item[0].score,
                    -item[1].physical_event.event.event_time.timestamp(),
                    item[0].physical_event_id,
                ),
            )
        )

    def _add_human_impact_signals(
        self, state: EvidenceWorldState, add_signal: _SignalAdder
    ) -> None:
        for key in ("fatalities", "injuries", "missing", "evacuations"):
            claim = state.claim(key)
            value = _claim_number(claim)
            if value is None or claim.current is None or value <= 0:
                continue
            evidence_ids = (claim.current.observation_id,)
            if key == "fatalities":
                add_signal(
                    "tr.priority.verified_fatalities",
                    "Verified current evidence reports one or more fatalities.",
                    55 if value < 10 else 70,
                    evidence_ids=evidence_ids,
                    priority_floor=IncidentPriority.CRITICAL,
                )
            elif key == "injuries":
                add_signal(
                    "tr.priority.verified_injuries",
                    "Verified current evidence reports injuries.",
                    45 if value >= 100 else 20,
                    evidence_ids=evidence_ids,
                    priority_floor=(
                        IncidentPriority.CRITICAL
                        if value >= 100
                        else IncidentPriority.MODERATE
                    ),
                )
            elif key == "missing":
                add_signal(
                    "tr.priority.verified_missing_people",
                    "Verified current evidence reports missing people.",
                    45 if value >= 10 else 30,
                    evidence_ids=evidence_ids,
                    priority_floor=(
                        IncidentPriority.CRITICAL
                        if value >= 10
                        else IncidentPriority.HIGH
                    ),
                )
            else:
                add_signal(
                    "tr.priority.verified_evacuations",
                    "Verified current evidence reports evacuations or displacement.",
                    35 if value >= 1_000 else 15,
                    evidence_ids=evidence_ids,
                    priority_floor=(
                        IncidentPriority.HIGH
                        if value >= 1_000
                        else IncidentPriority.MODERATE
                    ),
                )

    def _add_operational_signals(
        self, state: EvidenceWorldState, add_signal: _SignalAdder
    ) -> bool:
        ambiguity_found = False
        for claim in state.claims:
            current = claim.current
            if current is None:
                continue
            category = current.fact.category.casefold()
            value = current.fact.value
            evidence_ids = (current.observation_id,)
            if category in {"warning", "warnings", "tsunami_status"}:
                if _ACTIVE_WARNING.search(value) and not _NEGATED_WARNING.search(value):
                    add_signal(
                        "tr.priority.active_official_warning",
                        "Verified current evidence contains an active warning.",
                        30,
                        evidence_ids=evidence_ids,
                        priority_floor=IncidentPriority.HIGH,
                    )
            elif category in {
                "infrastructure",
                "infrastructure_disruption",
                "utilities",
            }:
                interpretation = _interpret_operational_impact(value)
                if interpretation == _ImpactInterpretation.NO_IMPACT:
                    continue
                if interpretation == _ImpactInterpretation.AMBIGUOUS:
                    ambiguity_found = True
                    add_signal(
                        "tr.priority.ambiguous_operational_impact",
                        "Current infrastructure evidence is ambiguous; review "
                        "priority rises rather than treating it as no impact.",
                        10,
                        evidence_ids=evidence_ids,
                        priority_floor=IncidentPriority.MODERATE,
                    )
                    continue
                add_signal(
                    "tr.priority.infrastructure_disruption",
                    "Verified current evidence reports infrastructure disruption.",
                    20,
                    evidence_ids=evidence_ids,
                    priority_floor=IncidentPriority.MODERATE,
                )
            elif category in {"damage", "physical_damage"}:
                interpretation = _interpret_operational_impact(value)
                if interpretation == _ImpactInterpretation.NO_IMPACT:
                    continue
                if interpretation == _ImpactInterpretation.AMBIGUOUS:
                    ambiguity_found = True
                    add_signal(
                        "tr.priority.ambiguous_operational_impact",
                        "Current damage evidence is ambiguous; review priority "
                        "rises rather than treating it as no impact.",
                        10,
                        evidence_ids=evidence_ids,
                        priority_floor=IncidentPriority.MODERATE,
                    )
                    continue
                severe = bool(_SEVERE_DAMAGE.search(value))
                add_signal(
                    "tr.priority.physical_damage",
                    "Verified current evidence reports physical damage.",
                    35 if severe else 15,
                    evidence_ids=evidence_ids,
                    priority_floor=(
                        IncidentPriority.HIGH if severe else IncidentPriority.MODERATE
                    ),
                )
        return ambiguity_found


def _interpret_operational_impact(value: str) -> _ImpactInterpretation:
    """Classify bounded impact wording without treating bare operational as negation."""
    clause_results: list[_ImpactInterpretation] = []
    for clause in _CLAUSE_BOUNDARY.split(value):
        normalized = clause.strip()
        if not normalized:
            continue
        if _AMBIGUOUS_OPERATIONAL_IMPACT.search(normalized):
            clause_results.append(_ImpactInterpretation.AMBIGUOUS)
        elif _EXPLICIT_NO_OPERATIONAL_IMPACT.search(normalized):
            clause_results.append(_ImpactInterpretation.NO_IMPACT)
        elif _OPERATIONAL_IMPACT.search(normalized):
            clause_results.append(_ImpactInterpretation.IMPACT)
        elif _IRRELEVANT_OPERATIONAL_CONTEXT.search(normalized):
            clause_results.append(_ImpactInterpretation.NO_IMPACT)
        else:
            clause_results.append(_ImpactInterpretation.AMBIGUOUS)
    if _ImpactInterpretation.IMPACT in clause_results:
        return _ImpactInterpretation.IMPACT
    if _ImpactInterpretation.AMBIGUOUS in clause_results or not clause_results:
        return _ImpactInterpretation.AMBIGUOUS
    return _ImpactInterpretation.NO_IMPACT


def _claim_number(claim: ClaimEvidenceState) -> float | None:
    if claim.current is None:
        return None
    match = _NUMBER.search(claim.current.fact.value.replace(",", ""))
    return None if match is None else float(match.group())


def _intensity_level(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"[1-7]", value)
    return None if match is None else int(match.group())


def _score_priority(score: int) -> IncidentPriority:
    if score >= 70:
        return IncidentPriority.CRITICAL
    if score >= 40:
        return IncidentPriority.HIGH
    if score >= 15:
        return IncidentPriority.MODERATE
    return IncidentPriority.LOW


def _max_priority(
    first: IncidentPriority, second: IncidentPriority
) -> IncidentPriority:
    return first if _PRIORITY_ORDER[first] >= _PRIORITY_ORDER[second] else second
