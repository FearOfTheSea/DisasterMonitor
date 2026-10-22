"""Bounded GDELT TOC archive traversal; publisher retrieval alone establishes facts."""

import gzip
import io
import ipaddress
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from disaster_monitor.domain.collection import (
    CollectionPage,
    CollectionPartition,
    CollectionProviderError,
)
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.collection_http import CollectionHttp
from disaster_monitor.infrastructure.news.public_documents import public_document_host

_MINUTE_ORDER = (1, 2, 0, *range(3, 15))
_NOTICE = (
    "GDELT public archive: supported-hazard headline leads only. "
    "Archive dates describe indexing, never publisher publication or event onset. "
    "Publisher retrieval determines reporting-window eligibility. "
    "Continuation checks every index minute, prioritizing heartbeat minutes; "
    "a cold historical scan can require thousands of requests. "
    "The newest five minutes, unsupported headline wording and hazards mentioned "
    "only in article bodies are not covered."
)


class GdeltArchiveCollectionProvider:
    source_id = "gdelt-archive-discovery"
    supports_alternates = False
    supports_time_filter = True
    queries = ("supported-hazard-headlines",)
    endpoint = "https://data.gdeltproject.org/gdeltv5/weblegacy/ngrams/"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15,
        minimum_interval: float = 1,
        maximum_decoded_bytes: int = 8_000_000,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1000 <= maximum_decoded_bytes <= 16_000_000:
            raise ValueError(
                "Archive decoded byte bound must be between1000 and16000000."
            )
        self._maximum_decoded_bytes = maximum_decoded_bytes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._http = CollectionHttp(
            client=client,
            timeout_seconds=timeout_seconds,
            minimum_interval=minimum_interval,
        )

    async def fetch_page(self, partition: CollectionPartition) -> CollectionPage:
        minutes, index = self._position(partition)
        if not minutes:
            return CollectionPage(saturated=True, notices=(_NOTICE,))
        minute = minutes[index]
        name = minute.strftime("%Y%m%d%H%M00")
        response = await self._http.get_bytes(
            self.endpoint + name + ".toc.json.gz", {}, accepted_statuses=(200, 404)
        )
        leads: tuple[NewsFeedItem, ...] = ()
        notices = [_NOTICE]
        if response.status_code == 404:
            notices.append(
                f"GDELT archive HTTP404 at index minute {minute.isoformat()}; "
                "no file was available. This does not establish absence of reporting."
            )
        else:
            leads, invalid = self._leads(response.body, minute, name)
            if invalid:
                notices.append(
                    f"GDELT archive excluded {invalid} invalid metadata rows."
                )
        next_cursor = (
            f"{max(minutes).strftime('%Y%m%d%H%M00')}:{index + 1}"
            if index + 1 < len(minutes)
            else None
        )
        return CollectionPage(
            leads=leads,
            next_cursor=next_cursor,
            # Headline-only filtering and index-time bounds are not complete
            # publication coverage, even after every archive minute is checked.
            saturated=True,
            notices=tuple(notices),
            requested_start=minute,
            requested_end=minute + timedelta(minutes=1),
        )

    def _position(
        self, partition: CollectionPartition
    ) -> tuple[tuple[datetime, ...], int]:
        def invalid() -> CollectionProviderError:
            return CollectionProviderError(
                "invalid_response", "GDELT archive continuation is invalid."
            )

        if (
            partition.query not in self.queries
            or partition.alternate_for
            or partition.end - partition.start > timedelta(days=32)
        ):
            raise invalid()
        lower = partition.start.astimezone(UTC)
        if lower.second or lower.microsecond:
            lower = lower.replace(second=0, microsecond=0) + timedelta(minutes=1)
        safe = self._clock().astimezone(UTC) - timedelta(minutes=5)
        upper = min(partition.end - timedelta(microseconds=1), safe).replace(
            second=0, microsecond=0
        )
        index = 0
        if partition.cursor:
            if not re.fullmatch(r"\d{14}:\d{1,5}", partition.cursor):
                raise invalid()
            value, position = partition.cursor.split(":")
            try:
                frozen = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            except ValueError as error:
                raise invalid() from error
            if frozen.second or not lower <= frozen <= upper:
                raise invalid()
            upper, index = frozen, int(position)
        count = int((upper - lower).total_seconds() // 60) + 1
        if count <= 0:
            if partition.cursor:
                raise invalid()
            return (), 0
        if index >= count:
            raise invalid()
        minutes = tuple(
            sorted(
                (lower + timedelta(minutes=i) for i in range(count)),
                key=lambda minute: (
                    _MINUTE_ORDER.index(minute.minute % 15),
                    -minute.timestamp(),
                ),
            )
        )
        return minutes, index

    def _leads(
        self, body: bytes, minute: datetime, name: str
    ) -> tuple[tuple[NewsFeedItem, ...], int]:
        try:
            if body[:2] == b"\x1f\x8b":
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as archive:
                    body = archive.read(self._maximum_decoded_bytes + 1)
            if len(body) > self._maximum_decoded_bytes:
                raise CollectionProviderError(
                    "invalid_response", "GDELT archive exceeded the decoded byte limit."
                )
            lines = body.decode("utf8").splitlines()
            if len(lines) > 50_000 or not any(line.strip() for line in lines):
                raise ValueError("Archive has no bounded record list")
            rows = [json.loads(line) for line in lines if line.strip()]
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("Archive rows must be objects")
        except (ValueError, UnicodeError, OSError, EOFError) as error:
            raise CollectionProviderError(
                "invalid_response", "GDELT archive is malformed or invalid."
            ) from error
        leads: dict[str, NewsFeedItem] = {}
        invalid = 0
        for row in rows:
            lead = _lead(row, minute, self.endpoint + name + ".toc.json.gz")
            if lead is None:
                invalid += 1
            elif disasters_in_text(lead.title):
                leads.setdefault(lead.canonical_url, lead)
        return tuple(leads.values()), invalid

    async def aclose(self) -> None:
        await self._http.aclose()


def _lead(
    row: dict[str, Any], minute: datetime, archive_url: str
) -> NewsFeedItem | None:
    title, url, identifier = row.get("title"), row.get("url"), row.get("ID")
    if (
        not isinstance(title, str)
        or not title.strip()
        or len(title) > 2000
        or not isinstance(url, str)
        or len(url) > 4096
        or type(identifier) is not int
        or identifier < 0
        or not isinstance(row.get("date"), str)
    ):
        return None
    host = public_document_host(url)
    if host is None:
        return None
    try:
        if not ipaddress.ip_address(host).is_global:
            return None
    except ValueError:
        # Domain names are resolved and pinned by the publisher reader, not here.
        pass
    try:
        stamp = datetime.fromisoformat(row["date"].replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.astimezone(UTC) != minute:
            return None
        return NewsFeedItem(
            external_id=f"{archive_url}#{identifier}",
            publisher=host,
            title=title.strip(),
            canonical_url=url,
            published_at=None,
            updated_at=None,
            indexed_at=minute,
            discovery_hint=title.strip(),
            search_title=" ".join(title.split())[:300],
        )
    except ValueError:
        return None
