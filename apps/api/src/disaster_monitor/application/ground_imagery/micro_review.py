"""Aggregate independent labels without changing imagery authority."""

from dataclasses import dataclass

from disaster_monitor.domain.imagery.analysis import (
    AnalyticalFindingReview,
    AnalyticalImageryFinding,
    FindingReviewDecision,
)


@dataclass(frozen=True, slots=True)
class ImageryMicroReviewSummary:
    finding_id: str
    finding_sha256: str
    independent_reviewer_count: int
    accepted_fraction: float
    supports_analytical_confidence: bool
    evidence_role: str = "analytical_observation"
    official_damage_claim: bool = False


def summarize_micro_reviews(
    finding: AnalyticalImageryFinding,
    reviews: tuple[AnalyticalFindingReview, ...],
    *,
    minimum_reviewers: int = 2,
) -> ImageryMicroReviewSummary:
    if minimum_reviewers < 2:
        raise ValueError("Micro-review confidence requires independent reviewers.")
    matching = tuple(
        item
        for item in reviews
        if item.finding_id == finding.finding_id
        and item.finding_sha256 == finding.sha256
    )
    reviewer_ids = {item.reviewer_id for item in matching}
    if len(reviewer_ids) != len(matching):
        raise ValueError("Each reviewer may contribute one label per finding version.")
    accepted = sum(item.decision is FindingReviewDecision.ACCEPTED for item in matching)
    count = len(matching)
    accepted_fraction = accepted / count if count else 0.0
    return ImageryMicroReviewSummary(
        finding_id=finding.finding_id,
        finding_sha256=finding.sha256,
        independent_reviewer_count=count,
        accepted_fraction=accepted_fraction,
        supports_analytical_confidence=(
            count >= minimum_reviewers and accepted_fraction >= 0.5
        ),
    )


__all__ = ["ImageryMicroReviewSummary", "summarize_micro_reviews"]
