from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from disaster_monitor.domain.disaster import Disaster, SourceReference
from disaster_monitor.domain.news import (
    IncidentCandidate,
    IncidentCandidateStatus,
    NewsFeedItem,
    NewsObservation,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_news_candidate_survives_repository_recreation(
    postgres_dsn: str,
) -> None:
    repository = PostgresOperationalRepository(postgres_dsn)
    await repository.migrate()
    now = datetime.now(UTC)
    identity = uuid4().hex
    source = SourceReference(
        source_id="gdelt-news",
        publisher="Associated Press",
        title="Major wildfire forces evacuations near Test Region",
        canonical_url=f"https://apnews.com/article/{identity}",
        published_at=now - timedelta(hours=1),
        updated_at=None,
        retrieved_at=now,
    )
    candidate = IncidentCandidate(
        candidate_id=f"news-candidate:{identity}",
        revision_id=f"news-candidate:{identity}:1",
        disaster=Disaster.WILDFIRE,
        location="Test Region",
        event_time=now - timedelta(hours=1),
        status=IncidentCandidateStatus.PROVISIONAL_NEWS_DETECTED,
        sources=(source,),
        news_break_at=now - timedelta(hours=1),
        first_observed_at=now,
        candidate_created_at=now,
    )

    assert await repository.append_incident_candidate(candidate)
    reopened = PostgresOperationalRepository(postgres_dsn)

    assert candidate in await reopened.latest_incident_candidates(
        since=now - timedelta(days=1)
    )


@pytest.mark.postgres
async def test_postgres_persists_unknown_publication_and_distinct_indexing(
    postgres_dsn,
):
    repository = PostgresOperationalRepository(postgres_dsn)
    await repository.migrate()
    now = datetime.now(UTC)
    identity = uuid4().hex
    observation = NewsObservation(
        identity,
        "gdelt-news",
        NewsFeedItem(
            identity,
            "Unfamiliar News",
            "Drought reporting",
            f"https://news.example/{identity}",
            published_at=None,
            updated_at=None,
            indexed_at=now,
        ),
        now,
    )
    assert await repository.append_news_observation(observation)
    async with await psycopg.AsyncConnection.connect(postgres_dsn) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT published_at,indexed_at,observed_at FROM news_observation "
                "WHERE observation_id=%s",
                (identity,),
            )
            assert await cursor.fetchone() == (None, now, now)
