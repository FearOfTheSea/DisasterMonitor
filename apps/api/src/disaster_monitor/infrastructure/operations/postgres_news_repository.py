"""PostgreSQL persistence for immutable news observations and candidates."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from psycopg.rows import dict_row

from disaster_monitor.domain.disaster import Disaster, source_from_document
from disaster_monitor.domain.incident_watch_documents import source_document
from disaster_monitor.domain.news import (
    IncidentCandidate,
    IncidentCandidateStatus,
    NewsObservation,
)
from disaster_monitor.infrastructure.operations.postgres_repository_base import (
    PostgresRepositoryBase,
)


class PostgresNewsRepository(PostgresRepositoryBase):
    async def append_news_observation(self, observation: NewsObservation) -> bool:
        item = observation.item
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO news_observation(
                        observation_id, source_id, external_id, publisher, title,
                        canonical_url, published_at, updated_at, observed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (observation_id) DO NOTHING
                    """,
                    (
                        observation.observation_id,
                        observation.source_id,
                        item.external_id,
                        item.publisher,
                        item.title,
                        item.canonical_url,
                        item.published_at,
                        item.updated_at,
                        observation.observed_at,
                    ),
                )
                return cursor.rowcount == 1

    async def append_incident_candidate(self, candidate: IncidentCandidate) -> bool:
        async with await self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO incident_candidate_revision(
                        revision_id, candidate_id, disaster, location, event_time,
                        status, sources, news_break_at, first_observed_at,
                        candidate_created_at, verified_at, rejected_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
                    ON CONFLICT (revision_id) DO NOTHING
                    """,
                    (
                        candidate.revision_id,
                        candidate.candidate_id,
                        candidate.disaster.value,
                        candidate.location,
                        candidate.event_time,
                        candidate.status.value,
                        json.dumps(
                            [source_document(item) for item in candidate.sources]
                        ),
                        candidate.news_break_at,
                        candidate.first_observed_at,
                        candidate.candidate_created_at,
                        candidate.verified_at,
                        candidate.rejected_at,
                    ),
                )
                return cursor.rowcount == 1

    async def latest_incident_candidates(
        self, *, since: datetime
    ) -> tuple[IncidentCandidate, ...]:
        async with await self._connection() as connection:
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT DISTINCT ON (candidate_id)
                        revision_id, candidate_id, disaster, location, event_time,
                        status, sources, news_break_at, first_observed_at,
                        candidate_created_at, verified_at, rejected_at
                    FROM incident_candidate_revision
                    WHERE news_break_at >= %s
                    ORDER BY candidate_id, candidate_created_at DESC, revision_id DESC
                    """,
                    (since,),
                )
                rows = await cursor.fetchall()
        return tuple(
            sorted(
                (_candidate(row) for row in rows),
                key=lambda item: (item.news_break_at, item.candidate_id),
                reverse=True,
            )
        )


def _candidate(row: dict[str, Any]) -> IncidentCandidate:
    raw_sources = row["sources"]
    source_items = (
        json.loads(raw_sources) if isinstance(raw_sources, str) else raw_sources
    )
    return IncidentCandidate(
        revision_id=str(row["revision_id"]),
        candidate_id=str(row["candidate_id"]),
        disaster=Disaster(str(row["disaster"])),
        location=str(row["location"]),
        event_time=cast(datetime, row["event_time"]),
        status=IncidentCandidateStatus(str(row["status"])),
        sources=tuple(source_from_document(item) for item in source_items),
        news_break_at=cast(datetime, row["news_break_at"]),
        first_observed_at=cast(datetime, row["first_observed_at"]),
        candidate_created_at=cast(datetime, row["candidate_created_at"]),
        verified_at=cast(datetime | None, row["verified_at"]),
        rejected_at=cast(datetime | None, row["rejected_at"]),
    )
