"""Epistemically bounded visual analysis and output safety policy."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from disaster_monitor.application.multimodal import VisualAnalysisRequest
from disaster_monitor.application.ports.visual_analysis import VisualAnalyzer
from disaster_monitor.domain.multimodal import (
    AssetEventAssociation,
    DamageLevel,
    EventAssociationStatus,
    MultimodalAsset,
    VisualAnalysisConfiguration,
    VisualObservation,
    VisualObservationKind,
    VisualObservationStatus,
)

_PROHIBITED_QUESTION = re.compile(
    r"\b(?:casualt(?:y|ies)|deaths?|dead|killed|fatalit(?:y|ies)|identity|"
    r"identify\s+(?:the\s+)?person|who\s+is|missing\s+person|official\s+warning|"
    r"evacuation\s+order|government\s+decision|authoritative\s+total)\b",
    re.I,
)
_UNSAFE_NUMERIC_CLAIM = re.compile(
    r"\b\d+\b.{0,24}\b(?:dead|deaths?|killed|fatalit(?:y|ies)|casualt(?:y|ies)|"
    r"missing\s+people)\b|\b(?:dead|deaths?|killed|fatalit(?:y|ies)|"
    r"casualt(?:y|ies)|missing\s+people)\b.{0,24}\b\d+\b",
    re.I,
)


class VisualSafetyPolicy:
    """Non-compensatory denials for claims pixels cannot authorize."""

    def prohibited_question(self, question: str | None) -> bool:
        return bool(question and _PROHIBITED_QUESTION.search(question))

    def unsafe_answer(self, answer: str | None) -> bool:
        return bool(answer and _UNSAFE_NUMERIC_CLAIM.search(answer))


class VisualAnalysisService:
    """Create separate analytical observations with exact asset/config lineage."""

    def __init__(
        self,
        analyzer: VisualAnalyzer,
        *,
        clock: Callable[[], datetime],
        safety_policy: VisualSafetyPolicy | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._clock = clock
        self._safety = safety_policy or VisualSafetyPolicy()

    async def analyze(
        self,
        asset: MultimodalAsset,
        association: AssetEventAssociation,
        *,
        question: str | None,
    ) -> tuple[VisualObservation, ...]:
        if association.status != EventAssociationStatus.ASSOCIATED:
            return ()
        normalized_question = question.strip()[:500] if question else None
        prohibited = self._safety.prohibited_question(normalized_question)
        prediction = await self._analyzer.analyze(
            VisualAnalysisRequest(
                asset=asset,
                question=None if prohibited else normalized_question,
            )
        )
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        damage_status = (
            VisualObservationStatus.ABSTAINED
            if prediction.damage_level == DamageLevel.UNKNOWN
            else VisualObservationStatus.PRODUCED
        )
        observations = [
            self._observation(
                asset,
                association,
                kind=VisualObservationKind.DAMAGE_ASSESSMENT,
                status=damage_status,
                damage_level=prediction.damage_level,
                question=None,
                answer=None,
                answerable=None,
                confidence=prediction.damage_confidence,
                cues=prediction.damage_cues,
                configuration=prediction.configuration,
                now=now,
                safety_rules=(),
            )
        ]
        if normalized_question is not None:
            unsafe_answer = self._safety.unsafe_answer(prediction.answer)
            blocked = prohibited or unsafe_answer
            answerable = False if blocked else prediction.answerable
            status = (
                VisualObservationStatus.ABSTAINED
                if blocked or not prediction.answerable
                else VisualObservationStatus.PRODUCED
            )
            safety_rules = (
                ("mm.visual.prohibited_question",)
                if prohibited
                else ("mm.visual.unsafe_output_blocked",)
                if unsafe_answer
                else ()
            )
            observations.append(
                self._observation(
                    asset,
                    association,
                    kind=VisualObservationKind.VISUAL_QUESTION_ANSWER,
                    status=status,
                    damage_level=None,
                    question=normalized_question,
                    answer=None
                    if blocked or not prediction.answerable
                    else prediction.answer,
                    answerable=answerable,
                    confidence=(
                        None
                        if blocked or not prediction.answerable
                        else prediction.answer_confidence
                    ),
                    cues=() if blocked else prediction.answer_cues,
                    configuration=prediction.configuration,
                    now=now,
                    safety_rules=safety_rules,
                )
            )
        return tuple(observations)

    @staticmethod
    def _observation(
        asset: MultimodalAsset,
        association: AssetEventAssociation,
        *,
        kind: VisualObservationKind,
        status: VisualObservationStatus,
        damage_level: DamageLevel | None,
        question: str | None,
        answer: str | None,
        answerable: bool | None,
        confidence: float | None,
        cues: tuple[str, ...],
        configuration: VisualAnalysisConfiguration,
        now: datetime,
        safety_rules: tuple[str, ...],
    ) -> VisualObservation:
        material = "|".join(
            (
                asset.asset_id,
                association.association_id,
                kind.value,
                damage_level.value if damage_level else "",
                question or "",
                answer or "",
                configuration.analysis_version,
                configuration.model_id,
            )
        )
        uncertainty = (
            "The visual model abstained; no pixel-supported assertion is available."
            if status == VisualObservationStatus.ABSTAINED
            else (
                "Analytical visual estimate only; model confidence does not confer "
                "source or official authority."
            )
        )
        return VisualObservation(
            observation_id=(
                f"visual:{sha256(material.encode('utf-8')).hexdigest()[:24]}"
            ),
            asset_id=asset.asset_id,
            association_id=association.association_id,
            physical_event_id=association.physical_event_id,
            kind=kind,
            status=status,
            damage_level=damage_level,
            question=question,
            answer=answer,
            answerable=answerable,
            confidence=confidence,
            uncertainty=uncertainty,
            visual_cues=tuple(cues[:4]),
            configuration=configuration,
            created_at=now,
            safety_rule_ids=safety_rules,
        )
