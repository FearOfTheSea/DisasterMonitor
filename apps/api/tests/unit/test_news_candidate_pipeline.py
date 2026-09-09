from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.ingestion.news_candidates import (
    NewsCandidateIngestion,
)
from disaster_monitor.application.ingestion.news_jobs import NewsFeedScheduler
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.news import (
    IncidentCandidateStatus,
    NewsFeedItem,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)

NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)


class FakeNewsFeed:
    source_id = "ap-news"

    async def fetch_since(self, *, since: datetime, now: datetime):
        assert since == NOW - timedelta(minutes=30)
        assert now == NOW
        return (
            NewsFeedItem(
                external_id="ap-antalya-1",
                publisher="Associated Press",
                title="Wildfire forces evacuations near Antalya, Turkey",
                canonical_url="https://apnews.com/article/antalya-fire",
                published_at=NOW - timedelta(hours=2),
                updated_at=None,
            ),
        )


@pytest.mark.asyncio
async def test_news_ingestion_persists_observation_and_publishable_candidate() -> None:
    repository = InMemoryOperationalRepository()
    service = NewsCandidateIngestion(
        FakeNewsFeed(),
        repository,
        clock=lambda: NOW,
        lookback=timedelta(minutes=30),
    )

    result = await service.refresh()

    assert result.observations_seen == 1
    assert result.observations_inserted == 1
    assert result.candidates_inserted == 1
    candidates = await repository.latest_incident_candidates(
        since=NOW - timedelta(days=1)
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.disaster is Disaster.WILDFIRE
    assert candidate.status is IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED
    assert candidate.news_break_at == NOW - timedelta(hours=2)
    assert candidate.first_observed_at == NOW
    assert candidate.candidate_created_at == NOW
    assert candidate.location == "Antalya, Turkey"


@pytest.mark.asyncio
async def test_news_ingestion_is_idempotent() -> None:
    repository = InMemoryOperationalRepository()
    service = NewsCandidateIngestion(FakeNewsFeed(), repository, clock=lambda: NOW)

    first = await service.refresh()
    second = await service.refresh()

    assert first.observations_inserted == 1
    assert second.observations_inserted == 0
    assert second.candidates_inserted == 0


@pytest.mark.asyncio
async def test_non_disaster_headline_is_observed_but_not_promoted() -> None:
    class NonDisasterFeed:
        source_id = "reuters-news"

        async def fetch_since(self, *, since: datetime, now: datetime):
            return (
                NewsFeedItem(
                    external_id="markets-1",
                    publisher="Reuters",
                    title="Markets rise after central bank decision",
                    canonical_url="https://www.reuters.com/markets/example",
                    published_at=NOW,
                    updated_at=None,
                ),
            )

    repository = InMemoryOperationalRepository()
    result = await NewsCandidateIngestion(
        NonDisasterFeed(), repository, clock=lambda: NOW
    ).refresh()

    assert result.observations_inserted == 1
    assert result.candidates_inserted == 0
    assert (
        await repository.latest_incident_candidates(since=NOW - timedelta(days=1)) == ()
    )


@pytest.mark.asyncio
async def test_news_scheduler_enqueues_each_feed_once_per_interval() -> None:
    repository = InMemoryOperationalRepository()
    scheduler = NewsFeedScheduler(repository, ("ap-news", "gdelt-news"))

    assert await scheduler.enqueue_due(now=NOW) == 2
    assert await scheduler.enqueue_due(now=NOW) == 0
    assert {job.source_id for job in repository.jobs.values()} == {
        "ap-news",
        "gdelt-news",
    }


@pytest.mark.asyncio
async def test_discovery_feed_requires_a_versioned_major_publisher() -> None:
    class LocalOutletFeed:
        source_id = "gdelt-news"

        async def fetch_since(self, *, since: datetime, now: datetime):
            return (
                NewsFeedItem(
                    external_id="local-1",
                    publisher="unknown-local.example",
                    title="Major flood forces evacuations in Example Province",
                    canonical_url="https://unknown-local.example/flood",
                    published_at=NOW,
                    updated_at=None,
                ),
            )

    repository = InMemoryOperationalRepository()
    result = await NewsCandidateIngestion(
        LocalOutletFeed(), repository, clock=lambda: NOW
    ).refresh()

    assert result.observations_inserted == 1
    assert result.candidates_inserted == 0


@pytest.mark.asyncio
async def test_reports_for_same_hazard_place_and_day_form_one_candidate() -> None:
    repository = InMemoryOperationalRepository()

    class ReutersFeed:
        source_id = "reuters-news"

        async def fetch_since(self, *, since: datetime, now: datetime):
            return (
                NewsFeedItem(
                    external_id="reuters-antalya-1",
                    publisher="Reuters",
                    title="Major wildfire forces evacuations near Antalya, Turkey",
                    canonical_url="https://www.reuters.com/world/antalya-fire",
                    published_at=NOW - timedelta(hours=1),
                    updated_at=None,
                ),
            )

    await NewsCandidateIngestion(
        FakeNewsFeed(), repository, clock=lambda: NOW
    ).refresh()
    await NewsCandidateIngestion(ReutersFeed(), repository, clock=lambda: NOW).refresh()

    candidates = await repository.latest_incident_candidates(
        since=NOW - timedelta(days=1)
    )
    assert len(candidates) == 1
    assert {source.source_id for source in candidates[0].sources} == {
        "ap-news",
        "reuters-news",
    }
    assert candidates[0].news_break_at == NOW - timedelta(hours=2)
