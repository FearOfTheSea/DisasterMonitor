"""Bounded read-only pages over immutable JSON index entries and scan membership."""

import asyncio
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from disaster_monitor.application.ports.indexed_reporting import (
    IndexedReportingObservation,
    IndexedReportingPage,
    IndexReportingPosition,
    IndexReportingSnapshot,
)
from disaster_monitor.domain.news import NewsFeedItem

_LEAD = TypeAdapter(NewsFeedItem)


class SQLiteIndexedReportingReader:
    """No constructor migration, acquisition or queue mutation authority."""

    def __init__(self, path: Path) -> None:
        self._uri = path.resolve().as_uri() + "?mode=ro"

    async def read_page(
        self,
        scan_id: str,
        *,
        query: str,
        snapshot: IndexReportingSnapshot | None,
        after: IndexReportingPosition | None,
        limit: int,
    ) -> IndexedReportingPage | None:
        return await asyncio.to_thread(
            self._read, scan_id, query, snapshot, after, limit
        )

    def _read(
        self,
        scan_id: str,
        query: str,
        snapshot: IndexReportingSnapshot | None,
        after: IndexReportingPosition | None,
        limit: int,
    ) -> IndexedReportingPage | None:
        with closing(sqlite3.connect(self._uri, uri=True)) as db:
            db.execute("BEGIN")
            if (
                db.execute("SELECT 1 FROM scans WHERE id=?", (scan_id,)).fetchone()
                is None
            ):
                return None
            if snapshot is None:
                page_watermark = db.execute(
                    "SELECT COALESCE(MAX(p.rowid),0) FROM pages p WHERE EXISTS "
                    "(SELECT 1 FROM scan_work sw WHERE sw.scan=? AND sw.work=p.work)",
                    (scan_id,),
                ).fetchone()[0]
                membership_watermark = db.execute(
                    "SELECT COALESCE(MAX(rowid),0) FROM scan_work WHERE scan=?",
                    (scan_id,),
                ).fetchone()[0]
                snapshot = IndexReportingSnapshot(page_watermark, membership_watermark)
            db.create_function(
                "casefold",
                1,
                lambda value: (value or "").casefold(),
                deterministic=True,
            )
            position = after or IndexReportingPosition(snapshot.page + 1, -1)
            rows = db.execute(
                "SELECT p.rowid,p.token,p.acquired,w.provider,"
                "CAST(j.key AS INTEGER),j.value "
                # Drive from retained pages, not the much larger unfinished work
                # queue. CROSS JOIN keeps that order without adding a write index
                # or migrating the journal just to inspect its existing evidence.
                "FROM pages p CROSS JOIN work w ON w.id=p.work "
                "CROSS JOIN scan_work sw ON sw.work=p.work "
                "CROSS JOIN json_each(p.page,'$.leads') j "
                "WHERE sw.scan=? AND sw.rowid<=? AND p.rowid<=? "
                "AND p.rowid<=? "
                "AND (p.rowid<? OR (p.rowid=? AND CAST(j.key AS INTEGER)>?)) "
                "AND (?='' OR instr(casefold("
                "COALESCE(json_extract(j.value,'$.title'),'')||' '||"
                "COALESCE(json_extract(j.value,'$.publisher'),'')||' '||"
                "COALESCE(json_extract(j.value,'$.canonical_url'),'')||' '||"
                "COALESCE(json_extract(j.value,'$.discovery_hint'),'')||' '||"
                "COALESCE(json_extract(j.value,'$.search_title'),'')),?)>0) "
                "ORDER BY p.rowid DESC,CAST(j.key AS INTEGER) ASC LIMIT ?",
                (
                    scan_id,
                    snapshot.membership,
                    snapshot.page,
                    position.page,
                    position.page,
                    position.page,
                    position.item,
                    query,
                    query,
                    limit + 1,
                ),
            ).fetchall()
            selected = rows[:limit]
            return IndexedReportingPage(
                tuple(
                    IndexedReportingObservation(
                        f"{row[1]}:{row[4]}",
                        row[3],
                        datetime.fromtimestamp(row[2], UTC),
                        _LEAD.validate_json(row[5]),
                    )
                    for row in selected
                ),
                snapshot,
                IndexReportingPosition(selected[-1][0], selected[-1][4])
                if len(rows) > limit
                else None,
            )
