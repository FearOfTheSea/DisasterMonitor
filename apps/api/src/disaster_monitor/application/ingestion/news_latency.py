"""Deterministic latency comparison for direct publisher and indexed discovery."""

from dataclasses import dataclass
from statistics import median

from disaster_monitor.domain.news import NewsObservation


@dataclass(frozen=True, slots=True)
class NewsLatencyComparison:
    direct_source_id: str
    indexed_source_id: str
    direct_sample_count: int
    indexed_sample_count: int
    direct_median_seconds: float | None
    indexed_median_seconds: float | None
    sufficient_for_default_change: bool
    rationale: str


def compare_news_discovery_latency(
    observations: tuple[NewsObservation, ...],
    *,
    direct_source_id: str,
    indexed_source_id: str = "gdelt-news",
    minimum_samples_per_source: int = 30,
) -> NewsLatencyComparison:
    direct = _latencies(observations, direct_source_id)
    indexed = _latencies(observations, indexed_source_id)
    sufficient = (
        len(direct) >= minimum_samples_per_source
        and len(indexed) >= minimum_samples_per_source
    )
    return NewsLatencyComparison(
        direct_source_id=direct_source_id,
        indexed_source_id=indexed_source_id,
        direct_sample_count=len(direct),
        indexed_sample_count=len(indexed),
        direct_median_seconds=median(direct) if direct else None,
        indexed_median_seconds=median(indexed) if indexed else None,
        sufficient_for_default_change=sufficient,
        rationale=(
            "Both paths meet the minimum paired operating sample gate."
            if sufficient
            else "Keep existing discovery defaults until both paths have enough "
            "production observations."
        ),
    )


def _latencies(
    observations: tuple[NewsObservation, ...], source_id: str
) -> tuple[float, ...]:
    return tuple(
        max(0.0, (item.observed_at - item.item.published_at).total_seconds())
        for item in observations
        if item.source_id == source_id
    )


__all__ = ["NewsLatencyComparison", "compare_news_discovery_latency"]
