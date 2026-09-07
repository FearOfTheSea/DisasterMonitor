"""Bounded queries over retained evidence metadata."""

from disaster_monitor.application.ports.snapshots import SnapshotReader
from disaster_monitor.domain.operations import SourceSnapshotRecord


class EvidenceHistoryQuery:
    def __init__(self, reader: SnapshotReader) -> None:
        self._reader = reader

    async def execute(
        self, *, source_id: str | None = None, limit: int = 100
    ) -> tuple[SourceSnapshotRecord, ...]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 500
        ):
            raise ValueError("limit must be between 1 and 500")
        return await self._reader.snapshots(source_id=source_id, limit=limit)
