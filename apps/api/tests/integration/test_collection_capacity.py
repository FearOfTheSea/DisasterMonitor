"""Storage exhaustion must preserve the journal and stop before acknowledging work."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import shake_256
from uuid import uuid4

import pytest

from disaster_monitor.domain.collection import CollectionPage, CollectionPartition
from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.operations.sqlite_collection import (
    SQLiteCollectionJournal,
)

NOW = datetime(2026, 10, 20, tzinfo=UTC)
LIMIT = 1024 * 1024


def new_run():
    return DiscoveryRun(str(uuid4()), ReportingInterval.at_start(1, NOW))


def storage_noise(size: int, seed: int = 0) -> str:
    """Deterministic, diverse bytes still exhaust physical storage after compression."""
    return shake_256(f"storage-fixture-{seed}".encode()).hexdigest(size)


async def test_exhausted_page_keeps_cursor_and_prior_evidence_through_restart(tmp_path):
    from disaster_monitor.application.ports.discovery import DiscoveryCapacityError

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    run = new_run()
    partition = CollectionPartition("news", "flood", NOW - timedelta(days=1), NOW)
    await store.attach(run, (partition,), now=NOW, budget=10)
    first = await store.claim("search", "worker", now=NOW)
    assert await store.commit_page(
        first, CollectionPage(next_cursor="retained"), now=NOW
    )
    second = await store.claim("search", "worker", now=NOW)
    with pytest.raises(DiscoveryCapacityError):
        await store.commit_page(
            second,
            CollectionPage(next_cursor="must-not-advance", notices=("x" * LIMIT,)),
            now=NOW,
        )
    await store.suspend_at_capacity(now=NOW)
    retained = await store.read(run.scan_id)
    assert retained.status == "incomplete"
    assert retained.collection.can_continue
    assert any("storage capacity" in notice.lower() for notice in retained.issues)
    restarted = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    assert await restarted.read(run.scan_id) == retained
    assert (await restarted.snapshot(run.scan_id, now=NOW)).progress.pages_acquired == 1
    assert not await restarted.active_scans()
    assert await restarted.claim("search", "other", now=NOW) is None
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        size = db.execute("PRAGMA page_count").fetchone()[0]
        size *= db.execute("PRAGMA page_size").fetchone()[0]
        assert size <= LIMIT
    expanded = SQLiteCollectionJournal(path, maximum_bytes=4 * LIMIT)
    await expanded.continue_scan(run.scan_id, now=NOW, budget=10)
    resumed = await expanded.claim("search", "resume", now=NOW)
    assert resumed.partition.cursor == "retained"
    assert await expanded.commit_page(resumed, CollectionPage(), now=NOW)


async def test_snapshot_growth_and_new_scan_admission_are_bounded_without_eviction(
    tmp_path,
):
    from disaster_monitor.application.ports.discovery import DiscoveryCapacityError

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    original = new_run()
    await store.save(original)
    oversized = replace(original, issues=(storage_noise(LIMIT),))
    with pytest.raises(DiscoveryCapacityError):
        await store.save(oversized)
    assert await store.read(original.scan_id) == original
    with pytest.raises(DiscoveryCapacityError):
        await store.attach(
            replace(new_run(), issues=(storage_noise(LIMIT),)), (), now=NOW, budget=1
        )
    assert await store.recent() == (original,)


async def test_lower_configured_budget_preserves_existing_records_and_refuses_growth(
    tmp_path,
):
    from disaster_monitor.application.ports.discovery import DiscoveryCapacityError

    path = tmp_path / "journal.sqlite"
    original = replace(new_run(), issues=(storage_noise(2 * LIMIT),))
    await SQLiteCollectionJournal(path, maximum_bytes=4 * LIMIT).save(original)
    with sqlite3.connect(path) as db:
        assert (
            db.execute("PRAGMA page_count").fetchone()[0]
            * db.execute("PRAGMA page_size").fetchone()[0]
        ) > LIMIT
    bounded = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    assert await bounded.read(original.scan_id) == original
    with pytest.raises(DiscoveryCapacityError):
        await bounded.attach(new_run(), (), now=NOW, budget=1)
    assert await bounded.read(original.scan_id) == original


async def test_collection_stops_durably_instead_of_retrying_full_storage(tmp_path):
    from disaster_monitor.application.incidents.resumable_discovery import (
        ResumableDiscovery,
    )

    class Provider:
        source_id = "controlled"
        queries = ("flood",)
        supports_time_filter = True
        supports_alternates = False
        calls = 0

        async def fetch_page(self, partition):
            self.calls += 1
            return CollectionPage(notices=("x" * LIMIT,), next_cursor="next")

    class Reader:
        async def retrieve(self, lead):
            raise AssertionError("No article lead was acknowledged.")

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    provider = Provider()
    runtime = ResumableDiscovery((provider,), Reader(), store, clock=lambda: NOW)
    run = await runtime.start(1)
    await runtime.wait(run.scan_id)
    result = await runtime.get(run.scan_id)
    assert result.status == "incomplete"
    assert result.collection.can_continue
    assert provider.calls == 1
    assert not await store.active_scans()
    assert (await store.snapshot(run.scan_id, now=NOW)).progress.pages_acquired == 0
    assert await SQLiteCollectionJournal(path).read(run.scan_id) == result
    await runtime.aclose()


async def test_repeated_scan_metadata_cannot_grow_past_the_storage_budget(tmp_path):
    from disaster_monitor.application.ports.discovery import DiscoveryCapacityError

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    accepted = []
    for _ in range(200):
        run = replace(new_run(), issues=("retained" * 1024,))
        try:
            await store.attach(run, (), now=NOW, budget=1)
        except DiscoveryCapacityError:
            break
        accepted.append(run)
    else:
        pytest.fail("Repeated scan metadata did not reach a finite admission limit.")
    assert len(accepted) > 10
    assert {r.scan_id for r in await store.recent()} == {r.scan_id for r in accepted}
    await store.suspend_at_capacity(now=NOW)
    assert all(r.status == "incomplete" for r in await store.recent())
    assert not await store.active_scans()


async def test_pinned_reader_cannot_cause_unbounded_wal_growth(tmp_path):
    from disaster_monitor.application.ports.discovery import DiscoveryCapacityError

    path = tmp_path / "journal.sqlite"
    store = SQLiteCollectionJournal(path, maximum_bytes=LIMIT)
    run = replace(new_run(), issues=(storage_noise(70_000),))
    await store.save(run)
    reader = sqlite3.connect(path)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT run FROM scans").fetchall()
        for index in range(100):
            changed = replace(run, issues=(storage_noise(70_000, index + 1),))
            try:
                await store.save(changed)
            except DiscoveryCapacityError:
                break
            run = changed
        else:
            pytest.fail("Pinned-reader WAL never reached its admission limit.")
        assert path.with_name(path.name + "-wal").stat().st_size < 2 * LIMIT
        assert await store.read(run.scan_id) == run
    finally:
        reader.close()
    await store.save(replace(run, issues=("Reader released; writes resume.",)))


@pytest.mark.parametrize("suffix", ["", "/reprocess", "/continue"])
async def test_storage_admission_failure_is_explicit_http_507(tmp_path, suffix):
    from types import SimpleNamespace

    import httpx

    from disaster_monitor.application.ports.discovery import DiscoveryCapacityError
    from disaster_monitor.presentation.http.api import create_schema_app

    async def full(*args):
        raise DiscoveryCapacityError()

    app = create_schema_app()
    app.state.dependencies = SimpleNamespace(
        discovery_scans=SimpleNamespace(
            start=full, reprocess=full, continue_collection=full
        )
    )
    path = "/api/v1/discovery-scans"
    if suffix:
        path += f"/{uuid4()}{suffix}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json={"reporting_days": 1})
    assert response.status_code == 507
    assert "storage capacity" in response.json()["detail"]


async def test_capacity_during_final_projection_still_persists_incomplete_status(
    tmp_path,
):
    from disaster_monitor.application.incidents.resumable_discovery import (
        ResumableDiscovery,
    )
    from disaster_monitor.application.ports.discovery import DiscoveryCapacityError

    class FullOnFinalProjection(SQLiteCollectionJournal):
        async def save(self, run):
            if run.status != "running":
                raise DiscoveryCapacityError()
            await super().save(run)

    store = FullOnFinalProjection(tmp_path / "journal.sqlite")
    runtime = ResumableDiscovery((), None, store, clock=lambda: NOW)
    run = await runtime.start(1)
    await runtime.wait(run.scan_id)
    assert (await runtime.get(run.scan_id)).status == "incomplete"
    assert not await store.active_scans()
    await runtime.aclose()
