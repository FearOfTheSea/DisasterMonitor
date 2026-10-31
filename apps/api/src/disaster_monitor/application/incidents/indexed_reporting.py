"""Search source-index wording without promoting it into captured article evidence."""

import base64
import binascii
import json
from dataclasses import dataclass
from typing import cast

from disaster_monitor.application.ports.indexed_reporting import (
    IndexedReportingObservation,
    IndexedReportingReader,
    IndexReportingPosition,
    IndexReportingSnapshot,
)

PAGE_SIZE = 25
MAX_QUERY_LENGTH = 200


@dataclass(frozen=True, slots=True)
class IndexedReportingResult:
    observations: tuple[IndexedReportingObservation, ...]
    query: str
    snapshot: str
    next_cursor: str | None


class IndexedReportingQueries:
    def __init__(self, reader: IndexedReportingReader) -> None:
        self._reader = reader

    async def read(
        self, scan_id: str, *, query: str = "", cursor: str | None = None
    ) -> IndexedReportingResult:
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise ValueError("Search must contain at most 200 characters.")
        snapshot = None
        position = None
        if cursor is not None:
            snapshot, position = _read_cursor(cursor, scan_id, query)
        page = await self._reader.read_page(
            scan_id,
            query=query.casefold(),
            snapshot=snapshot,
            after=position,
            limit=PAGE_SIZE,
        )
        if page is None:
            raise LookupError("This scan has no retained news-index observations.")
        identity: list[str | int] = [
            scan_id,
            query,
            page.snapshot.page,
            page.snapshot.membership,
        ]
        return IndexedReportingResult(
            page.observations,
            query,
            _encode(identity),
            _encode([*identity, page.next_position.page, page.next_position.item])
            if page.next_position is not None
            else None,
        )


def _encode(values: list[str | int]) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode()
    ).decode()


def _read_cursor(
    cursor: str, scan_id: str, query: str
) -> tuple[IndexReportingSnapshot, IndexReportingPosition]:
    try:
        if len(cursor) > 2048:
            raise ValueError()
        values = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(values, list)
            or len(values) != 6
            or values[:2] != [scan_id, query]
            or any(
                type(value) is not int or not 0 <= value < 2**63 for value in values[2:]
            )
            or not 1 <= values[4] <= values[2]
        ):
            raise ValueError()
        numbers = cast(list[int], values[2:])
        return IndexReportingSnapshot(*numbers[:2]), IndexReportingPosition(
            *numbers[2:]
        )
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as error:
        raise ValueError(
            "Invalid indexed reporting continuation. Reload the search."
        ) from error
