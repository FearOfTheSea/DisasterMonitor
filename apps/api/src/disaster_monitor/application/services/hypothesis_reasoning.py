"""Bounded deterministic hypotheses derived only from canonical EW state."""

import re
from dataclasses import dataclass
from hashlib import sha256

from disaster_monitor.domain.disaster import (
    EvidenceDisposition,
    EvidenceFreshness,
    EvidenceWorldState,
    HypothesisArtifact,
    HypothesisFeature,
)

_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


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
        supporting: list[str] = []
        contradicting: list[str] = []
        stale: list[str] = []
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
                if state.freshness == EvidenceFreshness.STALE:
                    stale.append(state.observation.observation_id)
                    continue
                if value > 0:
                    supporting.append(state.observation.observation_id)
                elif value == 0:
                    contradicting.append(state.observation.observation_id)

        features: list[HypothesisFeature] = []
        if supporting:
            features.append(
                HypothesisFeature(
                    "ew.hypothesis.fresh_positive_human_impact",
                    f"{len(supporting)} fresh current/conflicting observation(s) "
                    "reported a value above zero.",
                    0.46,
                )
            )
        if contradicting:
            features.append(
                HypothesisFeature(
                    "ew.hypothesis.fresh_explicit_zero_human_impact",
                    f"{len(contradicting)} fresh current/conflicting observation(s) "
                    "explicitly reported zero.",
                    -0.46,
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
        if supporting and contradicting:
            probability = 0.5
            features.append(
                HypothesisFeature(
                    "ew.hypothesis.material_conflict_neutral",
                    "Fresh supporting and contradicting observations remain "
                    "materially unresolved.",
                    0.0,
                )
            )
        elif supporting:
            probability = 0.96
        elif contradicting:
            probability = 0.04
        else:
            probability = 0.5
            features.append(
                HypothesisFeature(
                    "ew.hypothesis.no_decisive_current_observation",
                    "No fresh numeric current/conflicting observation resolved the "
                    "proposition.",
                    0.0,
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
            supporting_evidence_ids=tuple(sorted(supporting)),
            contradicting_evidence_ids=tuple(sorted(contradicting)),
            evaluated_at=world_state.evaluated_at,
            state_version=world_state.state_version,
            rationale_features=tuple(features),
        )


def _numeric_value(value: str) -> float | None:
    match = _NUMBER.search(value.replace(",", ""))
    if match is None:
        return None
    return float(match.group())
