from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ingestion.news_latency import (
    compare_news_discovery_latency,
)
from disaster_monitor.domain.news import NewsFeedItem, NewsObservation

NOW = datetime(2026, 9, 15, 8, tzinfo=UTC)


def _observation(source_id: str, delay_minutes: int, index: int) -> NewsObservation:
    published = NOW - timedelta(minutes=delay_minutes)
    return NewsObservation(
        observation_id=f"observation:{source_id}:{index}",
        source_id=source_id,
        item=NewsFeedItem(
            external_id=f"item:{source_id}:{index}",
            publisher="Publisher",
            title="Major flood update",
            canonical_url=f"https://publisher.example/{source_id}/{index}",
            published_at=published,
            updated_at=None,
        ),
        observed_at=NOW,
    )


def test_latency_comparison_requires_enough_samples_before_default_change() -> None:
    observations = tuple(_observation("nasa", 5, index) for index in range(2)) + tuple(
        _observation("gdelt-news", 20, index) for index in range(2)
    )

    result = compare_news_discovery_latency(
        observations, direct_source_id="nasa", minimum_samples_per_source=3
    )

    assert result.direct_median_seconds == 300
    assert result.indexed_median_seconds == 1200
    assert result.sufficient_for_default_change is False
    assert "Keep existing" in result.rationale
