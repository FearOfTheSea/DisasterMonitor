"""Bounded deterministic hypotheses derived only from canonical EW state."""

import re
from dataclasses import dataclass
from hashlib import sha256

from disaster_monitor.domain.disaster import (
    EvidenceDisposition,
    EvidenceFreshness,
    EvidenceWorldState,
    FactStatus,
    HypothesisArtifact,
    HypothesisFeature,
)

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
HUMAN_IMPACT_STATUS_WEIGHTS = {
    FactStatus.CONFIRMED: 0.46,
    FactStatus.PRELIMINARY: 0.25,
    FactStatus.ESTIMATED: 0.15,
    FactStatus.DISPUTED: 0.0,
}


@dataclass(frozen=True, slots=True)
class HypothesisRule:
    """Declared proposition and canonical claim categories that affect it."""

    rule_id: str
    proposition: str
    claim_keys: tuple[str, ...]


HUMAN_IMPACT_RULE = HypothesisRule(
    rule_id="ew.hypothesis.material_human_impact.v1",
    proposition=(
        "The selected physical event has material human impact in the currently "
        "available evidence."
    ),
    claim_keys=("fatalities", "injuries", "missing"),
)


class HypothesisGenerator:
    """Evaluate a small declared rule set without retrieval or model inference."""

    def __init__(
        self, rules: tuple[HypothesisRule, ...] = (HUMAN_IMPACT_RULE,)
    ) -> None:
        self._rules = rules

    def generate(
        self, world_state: EvidenceWorldState
    ) -> tuple[HypothesisArtifact, ...]:
        """Generate inferred artifacts from canonical state and nothing else."""
        return tuple(self._evaluate(world_state, rule) for rule in self._rules)

    def _evaluate(
        self, world_state: EvidenceWorldState, rule: HypothesisRule
    ) -> HypothesisArtifact:
        positive_by_status: dict[FactStatus, list[str]] = {
            status: [] for status in HUMAN_IMPACT_STATUS_WEIGHTS
        }
        zero_by_status: dict[FactStatus, list[str]] = {
            status: [] for status in HUMAN_IMPACT_STATUS_WEIGHTS
        }
        stale: list[str] = []
        uncertain: dict[FactStatus, list[str]] = {
            FactStatus.PRELIMINARY: [],
            FactStatus.ESTIMATED: [],
            FactStatus.DISPUTED: [],
        }
        for claim_key in rule.claim_keys:
            claim = world_state.claim(claim_key)
            for state in claim.history:
                if state.disposition not in {
                    EvidenceDisposition.CURRENT,
                    EvidenceDisposition.CONFLICTING,
                }:
                    continue
                value = _numeric_value(state.observation.fact.value)
                if value is None:
                    continue
                status = state.observation.fact.status
                if status != FactStatus.CONFIRMED:
                    if status in uncertain:
                        uncertain[status].append(state.observation.observation_id)
                if state.freshness == EvidenceFreshness.STALE:
                    stale.append(state.observation.observation_id)
                    continue
                if status not in HUMAN_IMPACT_STATUS_WEIGHTS:
                    continue
                target = positive_by_status if value > 0 else zero_by_status
                if value >= 0:
                    target[status].append(state.observation.observation_id)

        features: list[HypothesisFeature] = []
        for status, weight in HUMAN_IMPACT_STATUS_WEIGHTS.items():
            positive = positive_by_status[status]
            zero = zero_by_status[status]
            if positive:
                features.append(
                    HypothesisFeature(
                        f"ew.hypothesis.{status.value}_positive_human_impact",
                        f"{len(positive)} fresh {status.value} source "
                        "observation(s) reported a value above zero.",
                        weight,
                    )
                )
            if zero:
                features.append(
                    HypothesisFeature(
                        f"ew.hypothesis.{status.value}_explicit_zero_human_impact",
                        f"{len(zero)} fresh {status.value} source observation(s) "
                        "explicitly reported zero.",
                        -weight,
                    )
                )
        if stale:
            features.append(
                HypothesisFeature(
                    "ew.hypothesis.stale_observation_not_decisive",
                    f"{len(stale)} stale observation(s) were retained but did not "
                    "change the bounded probability.",
                    0.0,
                )
            )
        positive_strength = max(
            (
                weight
                for status, weight in HUMAN_IMPACT_STATUS_WEIGHTS.items()
                if positive_by_status[status]
            ),
            default=0.0,
        )
        zero_strength = max(
            (
                weight
                for status, weight in HUMAN_IMPACT_STATUS_WEIGHTS.items()
                if zero_by_status[status]
            ),
            default=0.0,
        )
        if positive_strength and zero_strength:
            features.append(
                HypothesisFeature(
                    "ew.hypothesis.status_weighted_material_conflict",
                    "Fresh positive and explicit-zero observations remain in a "
                    "status-weighted conflict.",
                    0.0,
                )
            )
        probability = max(
            0.0,
            min(1.0, 0.5 + positive_strength - zero_strength),
        )
        if not positive_strength and not zero_strength:
            features.append(
                HypothesisFeature(
                    "ew.hypothesis.no_decisive_current_observation",
                    "No fresh numeric current/conflicting observation resolved the "
                    "proposition.",
                    0.0,
                )
            )
        supporting = tuple(
            sorted(
                evidence_id
                for status, evidence_ids in positive_by_status.items()
                if HUMAN_IMPACT_STATUS_WEIGHTS[status] > 0
                for evidence_id in evidence_ids
            )
        )
        contradicting = tuple(
            sorted(
                evidence_id
                for status, evidence_ids in zero_by_status.items()
                if HUMAN_IMPACT_STATUS_WEIGHTS[status] > 0
                for evidence_id in evidence_ids
            )
        )
        material = f"{rule.rule_id}|{world_state.state_version}"
        hypothesis_id = (
            f"hypothesis:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
        )
        return HypothesisArtifact(
            hypothesis_id=hypothesis_id,
            proposition=rule.proposition,
            probability=probability,
            supporting_evidence_ids=supporting,
            contradicting_evidence_ids=contradicting,
            evaluated_at=world_state.evaluated_at,
            state_version=world_state.state_version,
            rationale_features=tuple(features),
            uncertain_evidence_ids=tuple(
                sorted(
                    evidence_id
                    for evidence_ids in uncertain.values()
                    for evidence_id in evidence_ids
                )
            ),
        )


def _numeric_value(value: str) -> float | None:
    match = _NUMBER.search(value.replace(",", ""))
    if match is None:
        return None
    return float(match.group())
