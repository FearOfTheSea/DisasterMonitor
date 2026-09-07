from datetime import UTC, datetime

import pytest

from disaster_monitor.application.conversations.queries import (
    ConversationNotFoundError,
    ConversationQueries,
)
from disaster_monitor.application.evidence.queries import EvidenceHistoryQuery
from disaster_monitor.domain.conversation import Conversation, ConversationSummary


class TranscriptReader:
    def __init__(self) -> None:
        self.conversation = Conversation(
            conversation_id="conversation-1",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            messages=(),
        )

    async def get(self, conversation_id: str) -> Conversation | None:
        return self.conversation if conversation_id == "conversation-1" else None

    async def list(self) -> tuple[ConversationSummary, ...]:
        return ()


class SnapshotReaderFake:
    def __init__(self) -> None:
        self.requests: list[tuple[str | None, int]] = []

    async def snapshots(
        self, *, source_id: str | None = None, limit: int = 100
    ) -> tuple:
        self.requests.append((source_id, limit))
        return ()


@pytest.mark.asyncio
async def test_conversation_queries_need_only_read_access() -> None:
    reader = TranscriptReader()
    queries = ConversationQueries(reader)
    assert await queries.get("conversation-1") == reader.conversation
    assert await queries.list() == ()
    with pytest.raises(ConversationNotFoundError):
        await queries.get("missing")


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 501, True, 1.5])
async def test_invalid_history_bounds_fail_before_storage(limit: int) -> None:
    reader = SnapshotReaderFake()
    with pytest.raises(ValueError):
        await EvidenceHistoryQuery(reader).execute(limit=limit)
    assert reader.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 100, 500])
async def test_history_preserves_source_filter_and_valid_bounds(limit: int) -> None:
    reader = SnapshotReaderFake()
    assert (
        await EvidenceHistoryQuery(reader).execute(source_id="usgs", limit=limit) == ()
    )
    assert reader.requests == [("usgs", limit)]
