"""Reusable closed archive bins and separately refreshed recent index tails."""

from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ports.collection import (
    CollectionProvider,
    ImmutableIndexProvider,
)
from disaster_monitor.domain.collection import CollectionPartition
from disaster_monitor.domain.discovery import ReportingInterval

_BIN_SECONDS = 6 * 3600
_TAIL_REFRESH_SECONDS = 15 * 60


def plan_index_collection(
    interval: ReportingInterval,
    provider: CollectionProvider,
    *,
    observed_at: datetime,
    version: str,
) -> tuple[CollectionPartition, ...]:
    if not isinstance(provider, ImmutableIndexProvider):
        return ()
    safe = observed_at - provider.index_availability_delay
    lower = int(interval.start.timestamp()) // _BIN_SECONDS * _BIN_SECONDS
    upper = int(safe.timestamp()) // _BIN_SECONDS * _BIN_SECONDS
    retrieval_generation = f"{version}:{int(observed_at.timestamp()) // _BIN_SECONDS}"
    tail_generation = (
        f"{version}:tail:{int(observed_at.timestamp()) // _TAIL_REFRESH_SECONDS}"
    )
    partitions: list[CollectionPartition] = []
    # The publisher cutoff remains interval.end. Later index windows can expose
    # late-indexed, already-published reporting without admitting later publication.
    for stamp in range(upper, lower - 1, -_BIN_SECONDS):
        start = datetime.fromtimestamp(stamp, UTC)
        end = start + timedelta(seconds=_BIN_SECONDS)
        generation = f"{version}:index" if end <= safe else tail_generation
        partitions.extend(
            CollectionPartition(
                provider.source_id,
                query,
                start,
                end,
                generation=generation,
                priority=1,
                retrieval_generation=retrieval_generation,
            )
            for query in provider.queries
        )
    return tuple(partitions)
