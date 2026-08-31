from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from disaster_monitor.domain.disaster import (
    Disaster,
    IncidentChangeKind,
    IncidentWatch,
    IncidentWatchChange,
    IncidentWatchObservation,
    IncidentWatchScope,
    WatchCoverageState,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)

NOW = datetime(2026, 8, 31, 8, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_incident_watch_repository_matches_memory_semantics(
    postgres_dsn: str,
) -> None:
    repository = PostgresOperationalRepository(postgres_dsn)
    await repository.migrate()
    watch_id = f"incident-watch:test:{uuid4()}"
    selected_watch = IncidentWatch(
        watch_id=watch_id,
        disaster=Disaster.WILDFIRE,
        scope=IncidentWatchScope.worldwide(),
        enabled=True,
        refresh_interval_seconds=900,
        created_at=NOW,
        updated_at=NOW,
        next_refresh_at=NOW,
    )
    observation = IncidentWatchObservation.create(
        watch_id=watch_id,
        observed_at=NOW,
        coverage_state=WatchCoverageState.DEGRADED,
        incidents=(),
        provider_names=("Fixture provider",),
        provider_source_ids=("fixture-provider",),
        warnings=("Fixture provider timed out.",),
        successful=False,
        retryable=True,
    )
    change = IncidentWatchChange.create_coverage_change(
        watch=selected_watch,
        previous=None,
        current=observation,
    )

    try:
        assert await repository.create_watch(selected_watch)
        assert not await repository.create_watch(selected_watch)
        assert await repository.due_watches(now=NOW) == (selected_watch,)
        assert await repository.record_watch_refresh(observation, (change,)) == 1

        reopened = PostgresOperationalRepository(postgres_dsn)
        stored = await reopened.get_watch(watch_id)
        assert stored is not None
        assert stored.coverage_state is WatchCoverageState.DEGRADED
        assert stored.last_checked_at == NOW
        assert stored.next_refresh_at == NOW + timedelta(seconds=900)
        assert stored.unread_change_count == 1
        assert await reopened.latest_watch_observation(watch_id) == observation
        assert await reopened.latest_successful_watch_observation(watch_id) is None
        assert (await reopened.watch_changes(watch_id))[0].kind is (
            IncidentChangeKind.COVERAGE_CHANGED
        )
        assert (await reopened.watch_changes(watch_id))[0].source_ids == (
            "fixture-provider",
        )
        assert (
            await reopened.mark_watch_changes_read(
                watch_id, (change.change_id,), read_at=NOW
            )
            == 1
        )
        assert (await reopened.get_watch(watch_id)).unread_change_count == 0  # type: ignore[union-attr]
        disabled = await reopened.set_watch_enabled(
            watch_id, enabled=False, updated_at=NOW + timedelta(minutes=1)
        )
        assert disabled is not None and not disabled.enabled
        assert await reopened.due_watches(now=NOW + timedelta(days=1)) == ()
    finally:
        await repository.delete_watch(watch_id)
