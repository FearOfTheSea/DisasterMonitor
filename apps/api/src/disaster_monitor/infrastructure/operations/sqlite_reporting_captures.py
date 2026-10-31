"""Read exact archived observations without loading the full publisher corpus."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import TypeAdapter

from disaster_monitor.application.ports.reporting_captures import reporting_capture_id
from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.infrastructure.operations.sqlite_collection_capacity import (
    is_storage_full,
)

_ARTICLE = TypeAdapter(DiscoveryArticle)
_URL_BATCH_SIZE = 500


class SQLiteReportingCaptureReader:
    """Read the capture archive without collection or journal mutation authority."""

    def __init__(self, path: Path) -> None:
        self._uri = path.resolve().as_uri() + "?mode=ro"

    async def read_capture(
        self, capture_id: str, *, canonical_urls: tuple[str, ...]
    ) -> DiscoveryArticle | None:
        return await asyncio.to_thread(self._read, capture_id, canonical_urls)

    def _read(
        self, capture_id: str, canonical_urls: tuple[str, ...]
    ) -> DiscoveryArticle | None:
        with closing(sqlite3.connect(self._uri, uri=True)) as db:
            return read_reporting_capture(db, capture_id, canonical_urls)


def initialize_reporting_lookup(db: sqlite3.Connection) -> None:
    try:
        db.execute(
            "CREATE INDEX IF NOT EXISTS evidence_publisher_url "
            "ON evidence(json_extract(article, '$.source.canonical_url'))"
        )
    except sqlite3.Error as error:
        # Full storage must not make already-retained evidence inaccessible.
        # The same read can stream the corpus until a later open creates the index.
        if not is_storage_full(error):
            raise


def read_reporting_capture(
    db: sqlite3.Connection, capture_id: str, canonical_urls: tuple[str, ...]
) -> DiscoveryArticle | None:
    for start in range(0, len(canonical_urls), _URL_BATCH_SIZE):
        urls = canonical_urls[start : start + _URL_BATCH_SIZE]
        placeholders = ",".join("?" for _ in urls)
        for row in db.execute(
            "SELECT article FROM evidence WHERE "
            "json_extract(article, '$.source.canonical_url') IN (" + placeholders + ")",
            urls,
        ):
            article = _ARTICLE.validate_json(row[0])
            if reporting_capture_id(article) == capture_id:
                return article
    return None
