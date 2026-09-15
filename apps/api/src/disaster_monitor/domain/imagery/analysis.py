"""Immutable analytical imagery findings and operator review records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType


class FindingReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_FOLLOW_UP = "needs_follow_up"


@dataclass(frozen=True, slots=True)
class AnalyticalImageryFinding:
    """Versioned model output that can never represent an official extent."""

    finding_id: str
    algorithm_id: str
    algorithm_version: str
    source_product_ids: tuple[str, ...]
    metrics: Mapping[str, float]
    threshold_parameters: tuple[tuple[str, float], ...]
    interpretation: str
    evidence_role: str = "analytical_observation"
    authoritative_extent: bool = False

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.finding_id, self.algorithm_id, self.algorithm_version)
        ):
            raise ValueError("Analytical findings require stable versioned identity.")
        if not self.source_product_ids or any(
            not value.strip() for value in self.source_product_ids
        ):
            raise ValueError("Analytical findings require source product identity.")
        if self.evidence_role != "analytical_observation":
            raise ValueError("Imagery findings must remain analytical observations.")
        if self.authoritative_extent:
            raise ValueError(
                "Analytical imagery cannot become an authoritative extent."
            )
        if any(not key.strip() for key in self.metrics):
            raise ValueError("Analytical metric names must not be empty.")
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    @property
    def sha256(self) -> str:
        payload = {
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "source_product_ids": self.source_product_ids,
            "metrics": dict(self.metrics),
            "threshold_parameters": self.threshold_parameters,
            "evidence_role": self.evidence_role,
            "authoritative_extent": self.authoritative_extent,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalyticalFindingReview:
    """An attributed decision layered over an immutable analytical finding."""

    review_id: str
    finding_id: str
    finding_sha256: str
    decision: FindingReviewDecision
    reviewer_id: str
    reviewed_at: datetime
    annotation: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.review_id,
                self.finding_id,
                self.finding_sha256,
                self.reviewer_id,
            )
        ):
            raise ValueError("Finding reviews require identity and attribution.")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("Finding review times must be timezone-aware.")
        if self.annotation is not None and not self.annotation.strip():
            raise ValueError("A review annotation must not be empty.")

    @classmethod
    def create(
        cls,
        *,
        finding: AnalyticalImageryFinding,
        decision: FindingReviewDecision,
        reviewer_id: str,
        reviewed_at: datetime,
        annotation: str | None = None,
    ) -> AnalyticalFindingReview:
        material = "|".join(
            (
                finding.finding_id,
                finding.sha256,
                decision.value,
                reviewer_id,
                reviewed_at.isoformat(),
                annotation or "",
            )
        )
        return cls(
            review_id="imagery-review:"
            + hashlib.sha256(material.encode()).hexdigest()[:24],
            finding_id=finding.finding_id,
            finding_sha256=finding.sha256,
            decision=decision,
            reviewer_id=reviewer_id,
            reviewed_at=reviewed_at,
            annotation=annotation,
        )


__all__ = [
    "AnalyticalFindingReview",
    "AnalyticalImageryFinding",
    "FindingReviewDecision",
]
