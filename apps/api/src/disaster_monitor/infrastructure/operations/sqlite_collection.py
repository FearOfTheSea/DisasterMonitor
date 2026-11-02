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

from pydantic import TypeAdapter

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
    search_continuation_priority,
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
    CollectionLeadBudget,
    CollectionStorageBudget,
    is_storage_full,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_citations import (
    initialize_citation_schedule,
    register_citation_page,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_claims import (
    ACTIVE_COLLECTION_SCANS as _ACTIVE_SCANS,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_claims import (
    claim_collection_work,
    initialize_metadata_attempts,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_leads import (
    enqueue_retrieval_lead,
    initialize_retrieval_priorities,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_links import (
    attach_collection_descendants,
    link_collection_work,
)
from disaster_monitor.infrastructure.operations.sqlite_collection_searches import (
    enqueue_search_partition,
    initialize_search_priorities,
)
from disaster_monitor.infrastructure.operations.sqlite_reporting_captures import (
    initialize_reporting_lookup,
)
from disaster_monitor.infrastructure.operations.sqlite_request_schedule import (
    CollectionRequestSchedule,
    request_scope,
    retained_publisher_refusals,
)
from disaster_monitor.infrastructure.operations.sqlite_retained_observations import (
    initialize_retained_observation_lookup,
)

T = TypeVar("T")
PARTITION = TypeAdapter(CollectionPartition)
LEAD = TypeAdapter(NewsFeedItem)
PAGE = TypeAdapter(CollectionPage)
ARTICLE = TypeAdapter(DiscoveryArticle)

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
CREATE TABLE IF NOT EXISTS retrieval_rotation (
 id INTEGER PRIMARY KEY CHECK(id=1), claimed INTEGER NOT NULL
);
INSERT OR IGNORE INTO retrieval_rotation VALUES(1,0);
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
        bulk_index_providers: frozenset[str] = frozenset(),
        reserved_targeted_leads: int = 0,
        maximum_metadata_requests: int | None = None,
    ) -> None:
        if maximum_metadata_requests is not None and (
            isinstance(maximum_metadata_requests, bool)
            or not isinstance(maximum_metadata_requests, int)
            or maximum_metadata_requests < 1
        ):
            raise ValueError("Metadata request limit must be positive.")
        self._maximum_metadata_requests = maximum_metadata_requests
        self._path = path
        self._legacy = legacy
        self._lease_seconds = lease_seconds
        self._maximum_leads = maximum_leads
        self._lead_budget = CollectionLeadBudget(
            maximum_leads, bulk_index_providers, reserved_targeted_leads
        )
        self._storage = CollectionStorageBudget(path, maximum_bytes)
        self._pass_seconds = pass_seconds
        self._run_payloads = DiscoveryRunPayloads()
        self._write_lock = Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
            initialize_reporting_lookup(db)
            self._reuse_retained = initialize_retained_observation_lookup(db)
            initialize_metadata_attempts(db)
            columns = {row[1] for row in db.execute("PRAGMA table_info(work)")}
            if "alternate_depth" not in columns:
                db.execute(
                    "ALTER TABLE work ADD COLUMN alternate_depth INTEGER NOT"
                    " NULL DEFAULT 0"
                )
            initialize_search_priorities(db)
            initialize_citation_schedule(db)
            initialize_retrieval_priorities(
                db, priority_column_created="priority" not in columns
            )
            self._initialize_projection_recovery(db)
            db.execute(
                "CREATE INDEX IF NOT EXISTS work_acquisition_order "
                "ON work(kind,priority DESC,sequence,id)"
            )
            # Enqueue also allocates a global ordinal for existing partitions.
            # Its MAX lookup must not traverse the ledger inside the writer lock.
            try:
                db.execute("CREATE INDEX IF NOT EXISTS work_sequence ON work(sequence)")
            except sqlite3.Error as error:
                # An optimization must not hide retained views in a full journal.
                # A later open retries it when storage capacity is available.
                if not is_storage_full(error):
                    raise
            if "policy_deferrals" not in columns:
                db.execute(
                    "ALTER TABLE work ADD COLUMN policy_deferrals "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            self._retained_refusals = retained_publisher_refusals(db)

    def _initialize_projection_recovery(self, db: sqlite3.Connection) -> None:
        db.execute("BEGIN IMMEDIATE")
        try:
            scan_columns = {row[1] for row in db.execute("PRAGMA table_info(scans)")}
            if "projection_pending" not in scan_columns:
                db.execute(
                    "ALTER TABLE scans ADD COLUMN projection_pending INTEGER "
                    "NOT NULL DEFAULT 0"
                )
                # Older journals can have a closed pass whose terminal view was
                # never saved. Restore that work without reopening acquisition.
                for row in db.execute(
                    "SELECT id,run FROM scans WHERE id NOT IN "
                    "(SELECT scan FROM scan_capacity)"
                ).fetchall():
                    if self._run_payloads.decode(row["run"]).status == "running":
                        db.execute(
                            "UPDATE scans SET projection_pending=1 WHERE id=?",
                            (row["id"],),
                        )
            db.commit()
        except BaseException:
            db.rollback()
            raise

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
                "DO UPDATE SET run=excluded.run,projection_pending="
                "CASE WHEN ? THEN 0 ELSE scans.projection_pending END",
                (run.scan_id, payload, run.status != "running"),
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
        enqueue_search_partition(db, partition)

    def _attach_descendants(self, db: sqlite3.Connection, scan: str, key: str) -> None:
        attach_collection_descendants(db, scan, key)

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
                "INSERT INTO scans(id,run,pass_id) VALUES(?,?,?)",
                (run.scan_id, self._run_payloads.encode(run), pass_id),
            )
            for partition in partitions:
                self._add_work(db, partition)
                self._attach_descendants(db, run.scan_id, partition.key)

    async def continue_scan(
        self,
        scan_id: str,
        *,
        now: datetime,
        budget: int,
        partitions: tuple[CollectionPartition, ...] = (),
    ) -> None:
        await asyncio.to_thread(self._continue, scan_id, now, budget, partitions)

    def _continue(
        self,
        scan_id: str,
        now: datetime,
        budget: int,
        partitions: tuple[CollectionPartition, ...],
    ) -> None:
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
            for partition in partitions:
                self._add_work(db, partition)
                self._attach_descendants(db, scan_id, partition.key)

    async def claim(
        self, kind: WorkKind, worker: str, *, now: datetime, provider: str | None = None
    ) -> ClaimedCollectionWork | None:
        return await asyncio.to_thread(self._claim, kind, worker, now, provider)

    def _claim(
        self, kind: WorkKind, worker: str, now: datetime, provider: str | None
    ) -> ClaimedCollectionWork | None:
        with self._transaction() as db:
            return claim_collection_work(
                db,
                kind,
                worker,
                now=now,
                provider=provider,
                pass_seconds=self._pass_seconds,
                lease_seconds=self._lease_seconds,
                retained_refusals=self._retained_refusals,
                maximum_metadata_requests=self._maximum_metadata_requests,
                reuse_retained=self._reuse_retained,
            )

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
        link_collection_work(db, parent, child)

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
            # A new subscriber may advance article observation while this page
            # is in flight. Preserve its generation without changing ownership.
            partition = PARTITION.validate_json(
                db.execute(
                    "SELECT payload FROM work WHERE id=?", (work.work_id,)
                ).fetchone()[0]
            )
            new_urls = {item.canonical_url for item in page.leads}
            refusal = self._lead_budget.page_refusal(
                db, work.provider, new_urls, len(page.articles)
            )
            if refusal:
                self._record_failure(
                    db,
                    work,
                    "capacity_exhausted",
                    refusal,
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
                key = enqueue_retrieval_lead(
                    db,
                    item,
                    partition.retrieval_generation or partition.generation,
                )
                self._link_child(db, work.work_id, key)
                if partition.alternate_for:
                    db.execute("UPDATE work SET alternate_depth=1 WHERE id=?", (key,))
            for article in page.articles:
                self._evidence(db, work.work_id, article)
            for child in page.children:
                self._add_work(db, child)
                self._link_child(db, work.work_id, child.key)
            register_citation_page(db, work.work_id, partition, page.children)
            next_partition = replace(
                partition,
                cursor=page.next_cursor or "",
                defer_initial_request=False,
                priority=search_continuation_priority(partition),
            )
            state = (
                "pending"
                if page.next_cursor is not None
                else "saturated"
                if page.saturated
                else "done"
            )
            db.execute(
                "UPDATE work SET "
                "payload=?,state=?,priority=?,token=NULL,lease_until=NULL,attempts=0,"
                "outcome=?,detail=NULL,sequence=(SELECT MAX(sequence)+1 "
                "FROM work) WHERE id=?",
                (
                    PARTITION.dump_json(next_partition),
                    state,
                    next_partition.priority,
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
        if outcome == "capacity_exhausted" and work.kind == "search":
            # Another page from this source can hit the same admission limit.
            # Pause its shared pass, preserving retrieval and other providers.
            # Explicit continuation grants a fresh allowance without advancing
            # the rejected cursor or removing any retained lead.
            db.execute(
                "UPDATE pass_budget SET remaining=0 WHERE provider=? AND pass_id IN "
                "(SELECT s.pass_id FROM scans s JOIN scan_work sw ON sw.scan=s.id "
                "JOIN passes p ON p.id=s.pass_id WHERE sw.work=? AND p.active=1)",
                (work.provider, work.work_id),
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
                    "p.id=s.pass_id WHERE p.active=1 OR s.projection_pending=1"
                )
            )

    async def finish_pass(self, *, now: datetime) -> None:
        await asyncio.to_thread(self._finish_pass)

    def _finish_pass(self) -> None:
        with self._transaction(control=True) as db:
            db.execute(
                "UPDATE scans SET projection_pending=1 WHERE pass_id IN "
                "(SELECT id FROM passes WHERE active=1)"
            )
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
            db.execute(
                "UPDATE scans SET projection_pending=0 WHERE id IN "
                "(SELECT scan FROM scan_capacity)"
            )

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
                "THEN 'article-retrieval' ELSE w.provider END "
                "LEFT JOIN pass_budget m ON m.pass_id=s.pass_id "
                "AND m.provider='all-metadata' WHERE "
                "w.state IN ('pending','leased') "
                "AND COALESCE(b.remaining,s.budget)>0 "
                "AND (w.kind!='search' OR COALESCE(m.remaining,1)>0)",
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
            # Index pages repeat lead metadata already read from the unique-lead
            # table below. Retain only their projection context, one page at a time.
            pages_acquired = 0
            page_notices: list[str] = []
            supplemental: list[DiscoveryArticle] = []
            for saved_page in db.execute(
                "SELECT page FROM pages p JOIN scan_work sw ON "
                "sw.work=p.work WHERE sw.scan=?",
                (scan_id,),
            ):
                page = PAGE.validate_json(saved_page[0])
                pages_acquired += 1
                page_notices.extend(page.notices)
                supplemental.extend(page.supplemental)
            leads = tuple(
                LEAD.validate_json(r[0])
                for r in db.execute(
                    "SELECT DISTINCT l.lead FROM leads l JOIN work_leads wl "
                    "ON wl.url=l.url JOIN scan_work sw ON sw.work=wl.work "
                    "WHERE sw.scan=?",
                    (scan_id,),
                )
            )
            linked_evidence = {
                r[0]
                for r in db.execute(
                    "SELECT we.evidence FROM work_evidence we JOIN scan_work sw "
                    "ON sw.work=we.work WHERE sw.scan=?",
                    (scan_id,),
                )
            }
            evidence = []
            # A feed can stop listing an article that still qualifies for this
            # interval. The retained corpus is independent of acquisition routes.
            # Stream captures so out-of-window bodies do not accumulate in memory.
            for saved in db.execute("SELECT id,article FROM evidence"):
                article = ARTICLE.validate_json(saved[1])
                if saved[0] in linked_evidence or run.interval.may_include_retained(
                    article
                ):
                    evidence.append(article)
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
                    + page_notices
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
                pages_acquired=pages_acquired,
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
                tuple(evidence),
                leads,
                tuple(supplemental),
                progress,
            )
