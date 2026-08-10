"""Evidence-state-owned incident priority policy for internal attention routing."""

import re
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
_NEGATED_OPERATIONAL_IMPACT = re.compile(
    r"\b(?:no|none|not reported|without|unaffected|operational)\b", re.I
)

_PRIORITY_ORDER = {
    IncidentPriority.LOW: 0,
    IncidentPriority.MODERATE: 1,
    IncidentPriority.HIGH: 2,
    IncidentPriority.CRITICAL: 3,
}


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
        self._add_operational_signals(state, add)

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
    ) -> None:
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
                if _NEGATED_OPERATIONAL_IMPACT.search(value):
                    continue
                add_signal(
                    "tr.priority.infrastructure_disruption",
                    "Verified current evidence reports infrastructure disruption.",
                    20,
                    evidence_ids=evidence_ids,
                    priority_floor=IncidentPriority.MODERATE,
                )
            elif category in {"damage", "physical_damage"}:
                if _NEGATED_OPERATIONAL_IMPACT.search(value):
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
