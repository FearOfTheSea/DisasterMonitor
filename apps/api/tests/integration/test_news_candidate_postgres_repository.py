from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.domain.disaster import Disaster, SourceReference
from disaster_monitor.domain.news import IncidentCandidate, IncidentCandidateStatus
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
        source_id="ap-news",
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
