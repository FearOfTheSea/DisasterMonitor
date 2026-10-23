"""Local WAL journal: short fenced transactions, atomic pages and continuations."""

import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import TypeAdapter

from disaster_monitor.application.ports.collection import ARTICLE_RETRIEVAL_PROVIDER
from disaster_monitor.application.ports.discovery import (
    DISCOVERY_CAPACITY_NOTICE,
    DiscoveryCapacityError,
    DiscoveryStore,
)
from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    CollectionPage,
    CollectionPartition,
    CollectionSnapshot,
    FailureOutcome,
    WorkKind,
    lead_retrieval_priority,
)
from disaster_monitor.domain.discovery import (
    CollectionProgress,
    DiscoveryArticle,
    DiscoveryRun,
)
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.operations.collection_run_payloads import (
    DiscoveryRunPayloads,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_capacity import (
    CollectionStorageBudget,
    is_storage_full,
)
from disaster_monitor.infrastructure.operations.sqlite_request_schedule import (
    CollectionRequestSchedule,
    request_scope,
    retained_publisher_refusals,
)

T = TypeVar("T")
PARTITION = TypeAdapter(CollectionPartition)
LEAD = TypeAdapter(NewsFeedItem)
PAGE = TypeAdapter(CollectionPage)
ARTICLE = TypeAdapter(DiscoveryArticle)

# Read scheduling metadata once, without revisiting saved run blobs per work row.
_ACTIVE_SCANS = (
    "WITH active_scans AS MATERIALIZED ("
    "SELECT s.id,s.pass_id,p.budget FROM scans s "
    "JOIN passes p ON p.id=s.pass_id WHERE p.active=1 AND p.started>?) "
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS passes (
 id INTEGER PRIMARY KEY, active INTEGER NOT NULL, budget INTEGER NOT NULL,
 started REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS scans (
 id TEXT PRIMARY KEY, run BLOB NOT NULL, pass_id INTEGER
);
CREATE TABLE IF NOT EXISTS scan_capacity (
 scan TEXT PRIMARY KEY, stopped REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS work (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, provider TEXT NOT NULL,
 payload BLOB NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, token TEXT, lease_until REAL,
 due REAL NOT NULL DEFAULT 0, outcome TEXT, detail TEXT,
 sequence INTEGER NOT NULL DEFAULT 0, alternate_depth INTEGER NOT NULL DEFAULT 0,
 priority INTEGER NOT NULL DEFAULT 0, policy_deferrals INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scan_work (
 scan TEXT NOT NULL, work TEXT NOT NULL, PRIMARY KEY(scan,work)
);
CREATE TABLE IF NOT EXISTS work_links (
 parent TEXT NOT NULL, child TEXT NOT NULL, PRIMARY KEY(parent,child)
);
CREATE TABLE IF NOT EXISTS pass_budget (
 pass_id INTEGER NOT NULL, provider TEXT NOT NULL, remaining INTEGER NOT NULL,
 PRIMARY KEY(pass_id,provider)
);
CREATE TABLE IF NOT EXISTS cooldowns (
 provider TEXT PRIMARY KEY, until_time REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
 token TEXT PRIMARY KEY, work TEXT NOT NULL, provider TEXT NOT NULL,
 started REAL NOT NULL, finished REAL,
 outcome TEXT NOT NULL DEFAULT 'started', detail TEXT
);
CREATE TABLE IF NOT EXISTS pages (
 token TEXT PRIMARY KEY, work TEXT NOT NULL, page BLOB NOT NULL, acquired REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
 url TEXT PRIMARY KEY, lead BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS work_leads (
 work TEXT NOT NULL, url TEXT NOT NULL, PRIMARY KEY(work,url)
);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, article BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS work_evidence (
 work TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(work,evidence)
);
CREATE INDEX IF NOT EXISTS work_due ON work(kind,state,due,sequence);
CREATE INDEX IF NOT EXISTS scan_work_reverse ON scan_work(work,scan);
"""


class SQLiteCollectionJournal:
    def __init__(
        self,
        path: Path,
        *,
        legacy: DiscoveryStore | None = None,
        lease_seconds: float = 90,
        maximum_leads: int = 20_000,
        maximum_bytes: int = 512 * 1024 * 1024,
        pass_seconds: float = 180,
    ) -> None:
        self._path = path
        self._legacy = legacy
        self._lease_seconds = lease_seconds
        self._maximum_leads = maximum_leads
        self._storage = CollectionStorageBudget(path, maximum_bytes)
        self._pass_seconds = pass_seconds
        self._run_payloads = DiscoveryRunPayloads()
        self._write_lock = Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(work)")}
            if "alternate_depth" not in columns:
                db.execute(
                    "ALTER TABLE work ADD COLUMN alternate_depth INTEGER NOT"
                    " NULL DEFAULT 0"
                )
            if "priority" not in columns:
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute(
                        "ALTER TABLE work ADD COLUMN priority INTEGER NOT NULL "
                        "DEFAULT 0"
                    )
                    db.executemany(
                        "UPDATE work SET priority=? WHERE id=?",
                        (
                            (
                                lead_retrieval_priority(
                                    LEAD.validate_json(row["payload"])
                                ),
                                row["id"],
                            )
                            for row in db.execute(
                                "SELECT id,payload FROM work WHERE kind='retrieve' "
                                "AND state IN ('pending','leased')"
                            ).fetchall()
                        ),
                    )
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
            if "policy_deferrals" not in columns:
                db.execute(
                    "ALTER TABLE work ADD COLUMN policy_deferrals "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            db.execute("PRAGMA user_version=1")
            self._retained_refusals = retained_publisher_refusals(db)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            self._storage.configure(db)
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self, *, control: bool = False) -> Iterator[sqlite3.Connection]:
        # Workers and projection share this adapter. Queue its writes before
        # opening connections instead of spending SQLite's external busy timeout
        # competing with another transaction already admitted by this instance.
        with self._write_lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if not control:
                    self._storage.check_admission(db)
                yield db
                if not control:
                    self._storage.check_admission(db)
                db.commit()
            except sqlite3.Error as error:
                db.rollback()
                if is_storage_full(error):
                    raise DiscoveryCapacityError() from error
                raise
            except BaseException:
                db.rollback()
                raise

    async def save(self, run: DiscoveryRun) -> None:
        await asyncio.to_thread(self._save, run)

    def _save(self, run: DiscoveryRun) -> None:
        payload = self._run_payloads.encode(run)
        with self._transaction() as db:
            db.execute(
                "INSERT INTO scans(id,run) VALUES (?,?) ON CONFLICT(id) "
                "DO UPDATE SET run=excluded.run",
                (run.scan_id, payload),
            )

    async def read(self, scan_id: str) -> DiscoveryRun | None:
        run = await asyncio.to_thread(self._read, scan_id)
        return run or (await self._legacy.read(scan_id) if self._legacy else None)

    def _read(self, scan_id: str) -> DiscoveryRun | None:
        with self._connect() as db:
            row = db.execute("SELECT run FROM scans WHERE id=?", (scan_id,)).fetchone()
            if not row:
                return None
            return self._capacity_view(db, self._run_payloads.decode(row[0]))

    def _capacity_view(self, db: sqlite3.Connection, run: DiscoveryRun) -> DiscoveryRun:
        stopped = db.execute(
            "SELECT stopped FROM scan_capacity WHERE scan=?", (run.scan_id,)
        ).fetchone()
        if not stopped:
            return run
        progress = run.collection or CollectionProgress()
        return replace(
            run,
            status="incomplete",
            finished_at=datetime.fromtimestamp(stopped[0], UTC),
            collection=replace(progress, state="partial", can_continue=True),
            truncated=True,
            issues=tuple(dict.fromkeys((*run.issues, DISCOVERY_CAPACITY_NOTICE))),
        )

    async def recent(self) -> tuple[DiscoveryRun, ...]:
        runs = await asyncio.to_thread(self._recent)
        legacy = await self._legacy.recent() if self._legacy else ()
        combined = {run.scan_id: run for run in (*legacy, *runs)}
        return tuple(
            sorted(combined.values(), key=lambda r: r.interval.end, reverse=True)
        )

    def _recent(self) -> tuple[DiscoveryRun, ...]:
        with self._connect() as db:
            return tuple(
                self._capacity_view(db, self._run_payloads.decode(row[0]))
                for row in db.execute("SELECT run FROM scans")
            )

    def _pass(self, db: sqlite3.Connection, now: datetime, budget: int) -> int:
        row = db.execute(
            "SELECT id FROM passes WHERE active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            return int(row[0])
        cursor = db.execute(
            "INSERT INTO passes(active,budget,started) VALUES(1,?,?)",
            (budget, now.timestamp()),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def _add_work(self, db: sqlite3.Connection, partition: CollectionPartition) -> None:
        db.execute(
            "INSERT INTO work(id,kind,provider,payload,priority,sequence) "
            "VALUES(?,'search',?,?,?,(SELECT COALESCE(MAX(sequence),0)+1 FROM work)) "
            "ON CONFLICT(id) DO UPDATE SET "
            "priority=MAX(work.priority,excluded.priority)",
            (
                partition.key,
                partition.provider,
                PARTITION.dump_json(partition),
                partition.priority,
            ),
        )

    def _attach_descendants(self, db: sqlite3.Connection, scan: str, key: str) -> None:
        db.execute(
            "WITH RECURSIVE children(id) AS (SELECT ? UNION SELECT child FROM "
            "work_links JOIN children ON parent=children.id) INSERT OR IGNORE "
            "INTO scan_work SELECT ?,id FROM children",
            (key, scan),
        )

    async def attach(
        self,
        run: DiscoveryRun,
        partitions: tuple[CollectionPartition, ...],
        *,
        now: datetime,
        budget: int,
    ) -> None:
        await asyncio.to_thread(self._attach, run, partitions, now, budget)

    def _attach(
        self,
        run: DiscoveryRun,
        partitions: tuple[CollectionPartition, ...],
        now: datetime,
        budget: int,
    ) -> None:
        with self._transaction() as db:
            pass_id = self._pass(db, now, budget)
            db.execute(
                "INSERT INTO scans VALUES(?,?,?)",
                (run.scan_id, self._run_payloads.encode(run), pass_id),
            )
            for partition in partitions:
                self._add_work(db, partition)
                self._attach_descendants(db, run.scan_id, partition.key)

    async def continue_scan(self, scan_id: str, *, now: datetime, budget: int) -> None:
        await asyncio.to_thread(self._continue, scan_id, now, budget)

    def _continue(self, scan_id: str, now: datetime, budget: int) -> None:
        with self._transaction() as db:
            row = db.execute("SELECT run FROM scans WHERE id=?", (scan_id,)).fetchone()
            if not row:
                raise LookupError(
                    "Historical scan has no resumable page journal. Start a new scan."
                )
            run = self._run_payloads.decode(row[0])
            if run.reprocessed_from:
                raise ValueError(
                    "Continue the original collection, not a reprocessed result."
                )
            pass_id = self._pass(db, now, budget)
            db.execute("DELETE FROM scan_capacity WHERE scan=?", (scan_id,))
            db.execute(
                "UPDATE work SET state='pending',attempts=0 WHERE state='capacity' "
                "AND id IN (SELECT work FROM scan_work WHERE scan=?)",
                (scan_id,),
            )
            db.execute(
                "UPDATE scans SET pass_id=?,run=? WHERE id=?",
                (
                    pass_id,
                    self._run_payloads.encode(
                        replace(run, status="running", finished_at=None)
                    ),
                    scan_id,
                ),
            )

    async def claim(
        self, kind: WorkKind, worker: str, *, now: datetime, provider: str | None = None
    ) -> ClaimedCollectionWork | None:
        return await asyncio.to_thread(self._claim, kind, worker, now, provider)

    def _claim(
        self, kind: WorkKind, worker: str, now: datetime, provider: str | None
    ) -> ClaimedCollectionWork | None:
        timestamp = now.timestamp()
        with self._transaction() as db:
            rows = db.execute(
                _ACTIVE_SCANS + "SELECT DISTINCT w.*,s.pass_id,s.budget FROM work w "
                "JOIN scan_work sw ON sw.work=w.id "
                "JOIN active_scans s ON s.id=sw.scan "
                "LEFT JOIN cooldowns c ON c.provider=w.provider "
                "WHERE w.kind=? AND (w.state='pending' OR "
                "(w.state='leased' AND w.lease_until<=?)) "
                "AND w.due<=? AND COALESCE(c.until_time,0)<=? "
                "AND (? IS NULL OR w.provider=?) "
                "ORDER BY w.priority DESC,w.sequence,w.id",
                (
                    timestamp - self._pass_seconds,
                    kind,
                    timestamp,
                    timestamp,
                    timestamp,
                    provider,
                    provider,
                ),
            ).fetchall()
            schedule = CollectionRequestSchedule(db, self._retained_refusals)
            for row in rows:
                if schedule.ready_at(row) > timestamp:
                    continue
                if row["attempts"] - row["policy_deferrals"] >= 4:
                    db.execute(
                        "UPDATE work SET state='failed',outcome='attempts_exhausted',"
                        "detail='Worker lease expired after maximum attempts.' "
                        "WHERE id=?",
                        (row["id"],),
                    )
                    continue
                budget_key = (
                    row["provider"] if kind == "search" else "article-retrieval"
                )
                limit = row["budget"] if kind == "search" else row["budget"] * 4
                db.execute(
                    "INSERT OR IGNORE INTO pass_budget VALUES(?,?,?)",
                    (row["pass_id"], budget_key, limit),
                )
                remaining = db.execute(
                    "SELECT remaining FROM pass_budget WHERE pass_id=? AND provider=?",
                    (row["pass_id"], budget_key),
                ).fetchone()[0]
                if remaining <= 0:
                    continue
                token = worker + ":" + str(uuid4())
                db.execute(
                    "UPDATE pass_budget SET remaining=remaining-1 WHERE "
                    "pass_id=? AND provider=?",
                    (row["pass_id"], budget_key),
                )
                db.execute(
                    "UPDATE work SET "
                    "state='leased',token=?,lease_until=?,attempts=attempts+1"
                    " WHERE id=?",
                    (token, timestamp + self._lease_seconds, row["id"]),
                )
                db.execute(
                    "INSERT INTO attempts(token,work,provider,started) VALUES(?,?,?,?)",
                    (token, row["id"], row["provider"], timestamp),
                )
                return ClaimedCollectionWork(
                    row["id"],
                    token,
                    kind,
                    row["provider"],
                    PARTITION.validate_json(row["payload"])
                    if kind == "search"
                    else None,
                    LEAD.validate_json(row["payload"]) if kind == "retrieve" else None,
                    row["attempts"] + 1,
                    row["alternate_depth"],
                    row["policy_deferrals"],
                )
        return None

    def _owns(
        self, db: sqlite3.Connection, work: ClaimedCollectionWork, now: datetime
    ) -> bool:
        return (
            db.execute(
                "SELECT 1 FROM work WHERE id=? AND token=? AND "
                "state='leased' AND lease_until>?",
                (work.work_id, work.token, now.timestamp()),
            ).fetchone()
            is not None
        )

    def _link_child(self, db: sqlite3.Connection, parent: str, child: str) -> None:
        db.execute("INSERT OR IGNORE INTO work_links VALUES(?,?)", (parent, child))
        db.execute(
            "INSERT OR IGNORE INTO scan_work SELECT scan,? FROM scan_work WHERE work=?",
            (child, parent),
        )

    def _evidence(
        self, db: sqlite3.Connection, work_id: str, article: DiscoveryArticle
    ) -> None:
        payload = ARTICLE.dump_json(article)
        key = sha256(payload).hexdigest()
        db.execute("INSERT OR IGNORE INTO evidence VALUES(?,?)", (key, payload))
        db.execute("INSERT OR IGNORE INTO work_evidence VALUES(?,?)", (work_id, key))

    async def commit_page(
        self, work: ClaimedCollectionWork, page: CollectionPage, *, now: datetime
    ) -> bool:
        return await asyncio.to_thread(self._commit_page, work, page, now)

    def _commit_page(
        self, work: ClaimedCollectionWork, page: CollectionPage, now: datetime
    ) -> bool:
        payload = PAGE.dump_json(page)
        assert work.partition is not None
        with self._transaction() as db:
            if not self._owns(db, work, now):
                return False
            new_urls = {item.canonical_url for item in page.leads}
            existing = {row[0] for row in db.execute("SELECT url FROM leads")}
            evidence_count = db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            if (
                len(existing | new_urls) > self._maximum_leads
                or evidence_count + len(page.articles) > self._maximum_leads
            ):
                self._record_failure(
                    db,
                    work,
                    "capacity_exhausted",
                    "Evidence storage capacity reached; page not acknowledged.",
                    now,
                    None,
                )
                return False
            db.execute(
                "INSERT INTO pages VALUES(?,?,?,?)",
                (work.token, work.work_id, payload, now.timestamp()),
            )
            for item in page.leads:
                db.execute(
                    "INSERT OR IGNORE INTO leads VALUES(?,?)",
                    (item.canonical_url, LEAD.dump_json(item)),
                )
                db.execute(
                    "INSERT OR IGNORE INTO work_leads VALUES(?,?)",
                    (work.work_id, item.canonical_url),
                )
                key = sha256(
                    (
                        "retrieve|"
                        + item.canonical_url
                        + "|"
                        + work.partition.generation
                    ).encode()
                ).hexdigest()
                db.execute(
                    "INSERT OR IGNORE INTO "
                    "work(id,kind,provider,payload,priority,sequence) "
                    "VALUES(?,'retrieve',?,?,?,"
                    "(SELECT COALESCE(MAX(sequence),0)+1 FROM work))",
                    (
                        key,
                        ARTICLE_RETRIEVAL_PROVIDER,
                        LEAD.dump_json(item),
                        lead_retrieval_priority(item),
                    ),
                )
                self._link_child(db, work.work_id, key)
                if work.partition.alternate_for:
                    db.execute("UPDATE work SET alternate_depth=1 WHERE id=?", (key,))
            for article in page.articles:
                self._evidence(db, work.work_id, article)
            for child in page.children:
                self._add_work(db, child)
                self._link_child(db, work.work_id, child.key)
            next_partition = replace(work.partition, cursor=page.next_cursor or "")
            state = (
                "pending"
                if page.next_cursor is not None
                else "saturated"
                if page.saturated
                else "done"
            )
            db.execute(
                "UPDATE work SET "
                "payload=?,state=?,token=NULL,lease_until=NULL,attempts=0,"
                "outcome=?,detail=NULL,sequence=(SELECT MAX(sequence)+1 "
                "FROM work) WHERE id=?",
                (
                    PARTITION.dump_json(next_partition),
                    state,
                    "saturated" if page.saturated else "page_acquired",
                    work.work_id,
                ),
            )
            db.execute(
                "UPDATE attempts SET finished=?,outcome='page_acquired' WHERE token=?",
                (now.timestamp(), work.token),
            )
        return True

    async def commit_article(
        self,
        work: ClaimedCollectionWork,
        article: DiscoveryArticle,
        *,
        now: datetime,
        alternates: tuple[CollectionPartition, ...] = (),
    ) -> bool:
        return await asyncio.to_thread(
            self._commit_article, work, article, now, alternates
        )

    def _commit_article(
        self,
        work: ClaimedCollectionWork,
        article: DiscoveryArticle,
        now: datetime,
        alternates: tuple[CollectionPartition, ...],
    ) -> bool:
        with self._transaction() as db:
            if not self._owns(db, work, now):
                return False
            count = db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            if count >= self._maximum_leads:
                self._record_failure(
                    db,
                    work,
                    "capacity_exhausted",
                    "Evidence storage capacity reached; article task retained.",
                    now,
                    None,
                )
                return False
            self._evidence(db, work.work_id, article)
            for partition in alternates:
                self._add_work(db, partition)
                self._link_child(db, work.work_id, partition.key)
            db.execute(
                "UPDATE work SET "
                "state='done',outcome='article_retrieved',token=NULL,lease_until=NULL"
                " WHERE id=?",
                (work.work_id,),
            )
            db.execute(
                "UPDATE attempts SET "
                "finished=?,outcome='article_retrieved' WHERE token=?",
                (now.timestamp(), work.token),
            )
        return True

    async def fail(
        self,
        work: ClaimedCollectionWork,
        *,
        outcome: FailureOutcome,
        detail: str,
        now: datetime,
        retry_at: datetime | None = None,
        alternates: tuple[CollectionPartition, ...] = (),
    ) -> bool:
        return await asyncio.to_thread(
            self._fail, work, outcome, detail, now, retry_at, alternates
        )

    def _fail(
        self,
        work: ClaimedCollectionWork,
        outcome: FailureOutcome,
        detail: str,
        now: datetime,
        retry_at: datetime | None,
        alternates: tuple[CollectionPartition, ...],
    ) -> bool:
        with self._transaction() as db:
            if not self._owns(db, work, now):
                return False
            self._record_failure(db, work, outcome, detail, now, retry_at)
            for partition in alternates:
                self._add_work(db, partition)
                self._link_child(db, work.work_id, partition.key)
        return True

    def _record_failure(
        self,
        db: sqlite3.Connection,
        work: ClaimedCollectionWork,
        outcome: FailureOutcome,
        detail: str,
        now: datetime,
        retry_at: datetime | None,
    ) -> None:
        retry = retry_at is not None and (
            outcome == "policy_deferred" or work.attempts - work.policy_deferrals < 4
        )
        state = (
            "capacity"
            if outcome == "capacity_exhausted"
            else "pending"
            if retry
            else "refused"
            if outcome == "access_refused"
            else "failed"
        )
        db.execute(
            "UPDATE work SET "
            "state=?,due=?,outcome=?,detail=?,token=NULL,lease_until=NULL,"
            "policy_deferrals=policy_deferrals+?,"
            "sequence=(SELECT MAX(sequence)+1 FROM work) WHERE id=?",
            (
                state,
                retry_at.timestamp() if retry_at else 0,
                outcome,
                detail[:300],
                int(outcome == "policy_deferred"),
                work.work_id,
            ),
        )
        db.execute(
            "UPDATE attempts SET finished=?,outcome=?,detail=? WHERE token=?",
            (now.timestamp(), outcome, detail[:300], work.token),
        )
        if retry_at:
            row = db.execute(
                "SELECT * FROM work WHERE id=?", (work.work_id,)
            ).fetchone()
            db.execute(
                "INSERT INTO cooldowns VALUES(?,?) ON CONFLICT(provider) DO UPDATE SET "
                "until_time=MAX(until_time,excluded.until_time)",
                (request_scope(row), retry_at.timestamp()),
            )

    async def active_scans(self) -> tuple[str, ...]:
        return await asyncio.to_thread(self._active_scans)

    def _active_scans(self) -> tuple[str, ...]:
        with self._connect() as db:
            return tuple(
                row[0]
                for row in db.execute(
                    "SELECT s.id FROM scans s JOIN passes p ON "
                    "p.id=s.pass_id WHERE p.active=1"
                )
            )

    async def finish_pass(self, *, now: datetime) -> None:
        await asyncio.to_thread(self._finish_pass)

    def _finish_pass(self) -> None:
        with self._transaction(control=True) as db:
            db.execute("UPDATE passes SET active=0 WHERE active=1")

    async def suspend_at_capacity(
        self, *, now: datetime, scan_ids: tuple[str, ...] = ()
    ) -> None:
        await asyncio.to_thread(self._suspend_at_capacity, now, scan_ids)

    def _suspend_at_capacity(self, now: datetime, scan_ids: tuple[str, ...]) -> None:
        with self._transaction(control=True) as db:
            db.execute(
                "INSERT OR IGNORE INTO scan_capacity SELECT s.id,? FROM scans s "
                "JOIN passes p ON p.id=s.pass_id WHERE p.active=1",
                (now.timestamp(),),
            )
            db.executemany(
                "INSERT OR IGNORE INTO scan_capacity SELECT id,? FROM scans WHERE id=?",
                ((now.timestamp(), scan_id) for scan_id in scan_ids),
            )
            db.execute(
                "UPDATE attempts SET finished=?,outcome='capacity_exhausted',detail=? "
                "WHERE finished IS NULL AND token IN "
                "(SELECT token FROM work WHERE state='leased')",
                (now.timestamp(), "Discovery storage capacity reached."),
            )
            db.execute(
                "UPDATE work SET state='capacity',outcome='capacity_exhausted',"
                "token=NULL,lease_until=NULL WHERE state='leased'"
            )
            db.execute("UPDATE passes SET active=0 WHERE active=1")

    async def next_retry(self, *, now: datetime) -> datetime | None:
        return await asyncio.to_thread(self._next_retry, now)

    def _next_retry(self, now: datetime) -> datetime | None:
        with self._connect() as db:
            rows = db.execute(
                _ACTIVE_SCANS + "SELECT w.* "
                "FROM work w JOIN scan_work sw ON sw.work=w.id JOIN "
                "active_scans s ON s.id=sw.scan "
                "LEFT JOIN cooldowns c ON c.provider=w.provider "
                "LEFT JOIN pass_budget b ON b.pass_id=s.pass_id AND "
                "b.provider=CASE WHEN w.kind='retrieve' "
                "THEN 'article-retrieval' ELSE w.provider END WHERE "
                "w.state IN ('pending','leased') "
                "AND COALESCE(b.remaining,s.budget)>0",
                (now.timestamp() - self._pass_seconds,),
            ).fetchall()
            schedule = CollectionRequestSchedule(db, self._retained_refusals)
            retry = min(
                (max(schedule.ready_at(row), row["lease_until"] or 0) for row in rows),
                default=None,
            )
            return (
                datetime.fromtimestamp(max(retry, now.timestamp()), UTC)
                if retry is not None
                else None
            )

    async def snapshot(self, scan_id: str, *, now: datetime) -> CollectionSnapshot:
        return await asyncio.to_thread(self._snapshot, scan_id, now)

    def _snapshot(self, scan_id: str, now: datetime) -> CollectionSnapshot:
        with self._connect() as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT s.run,p.active FROM scans s LEFT JOIN passes p "
                "ON p.id=s.pass_id WHERE s.id=?",
                (scan_id,),
            ).fetchone()
            if not row:
                raise LookupError("Scan has no collection journal.")
            run = self._capacity_view(db, self._run_payloads.decode(row[0]))
            capacity_stopped = DISCOVERY_CAPACITY_NOTICE in run.issues
            work = db.execute(
                "SELECT w.*,c.until_time FROM work w JOIN scan_work sw ON sw.work=w.id "
                "LEFT JOIN cooldowns c ON c.provider=w.provider WHERE sw.scan=?",
                (scan_id,),
            ).fetchall()
            pages = tuple(
                PAGE.validate_json(r[0])
                for r in db.execute(
                    "SELECT page FROM pages p JOIN scan_work sw ON "
                    "sw.work=p.work WHERE sw.scan=?",
                    (scan_id,),
                )
            )
            leads = tuple(
                LEAD.validate_json(r[0])
                for r in db.execute(
                    "SELECT DISTINCT l.lead FROM leads l JOIN work_leads wl "
                    "ON wl.url=l.url JOIN scan_work sw ON sw.work=wl.work "
                    "WHERE sw.scan=?",
                    (scan_id,),
                )
            )
            evidence = tuple(
                ARTICLE.validate_json(r[0])
                for r in db.execute(
                    "SELECT DISTINCT e.article FROM evidence e JOIN "
                    "work_evidence we ON we.evidence=e.id JOIN scan_work sw "
                    "ON sw.work=we.work WHERE sw.scan=?",
                    (scan_id,),
                )
            )
            requests = tuple(
                (r[0], r[1])
                for r in db.execute(
                    "SELECT a.provider,COUNT(*) FROM attempts a JOIN "
                    "scan_work sw ON sw.work=a.work WHERE sw.scan=? GROUP BY"
                    " a.provider",
                    (scan_id,),
                )
            )
            searches = [w for w in work if w["kind"] == "search"]
            retrievals = [w for w in work if w["kind"] == "retrieve"]

            def pending(w: sqlite3.Row) -> bool:
                return w["state"] in ("pending", "leased", "capacity")

            remaining = sum(pending(w) for w in work)
            schedule = CollectionRequestSchedule(db, self._retained_refusals)
            retries = [
                deadline
                for w in work
                if pending(w)
                and (deadline := schedule.retry_deadline(w)) > now.timestamp()
            ]
            progressing = any(
                (w["state"] == "leased" and (w["lease_until"] or 0) > now.timestamp())
                or (
                    w["state"] in ("pending", "leased")
                    and schedule.ready_at(w) <= now.timestamp()
                    and (w["lease_until"] or 0) <= now.timestamp()
                )
                for w in work
            )
            notices = tuple(
                dict.fromkeys(
                    [w["detail"] for w in work if w["detail"]]
                    + [n for page in pages for n in page.notices]
                    + ([DISCOVERY_CAPACITY_NOTICE] if capacity_stopped else [])
                )
            )
            failed = sum(
                w["state"] in ("failed", "refused", "saturated") for w in searches
            )
            state: Any = (
                "collecting"
                if row[1]
                else "partial"
                if remaining or failed or capacity_stopped
                else "finished"
            )
            if retries and remaining and row[1] and not progressing:
                state = "waiting"
            progress = CollectionProgress(
                state=state,
                searches_pending=sum(pending(w) for w in searches),
                searches_completed=sum(w["state"] == "done" for w in searches),
                searches_refused=sum(
                    w["state"] in ("refused", "failed") for w in searches
                ),
                searches_saturated=sum(w["state"] == "saturated" for w in searches),
                pages_acquired=len(pages),
                leads_acquired=len(leads),
                articles_pending=sum(pending(w) for w in retrievals),
                articles_retrieved=len([a for a in evidence if a.text]),
                articles_unavailable=sum(
                    w["state"] in ("failed", "refused") for w in retrievals
                ),
                retry_at=datetime.fromtimestamp(min(retries), UTC) if retries else None,
                can_continue=bool(remaining or capacity_stopped),
                notices=notices,
                provider_requests=requests,
            )
            return CollectionSnapshot(
                run,
                evidence,
                leads,
                tuple(a for p in pages for a in p.supplemental),
                progress,
            )
