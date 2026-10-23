"""Publisher timing remains fenced and independent across persistent readers."""

import asyncio

import pytest

from disaster_monitor.infrastructure.operations.sqlite_public_document_access import (
    SQLitePublicDocumentAccess,
)


async def test_only_one_concurrent_reader_claims_a_host_but_other_hosts_are_ready(
    tmp_path,
):
    path = tmp_path / "access.sqlite"
    first, second = SQLitePublicDocumentAccess(path), SQLitePublicDocumentAccess(path)
    reservations = await asyncio.gather(
        first.claim("same.example", now=1000, lease_seconds=20),
        second.claim("same.example", now=1000, lease_seconds=20),
    )
    assert sum(r.token is not None for r in reservations) == 1
    waiting = next(r for r in reservations if r.token is None)
    assert waiting.retry_after_seconds == 20
    assert (await second.claim("other.example", now=1000, lease_seconds=20)).token


async def test_unfinished_request_counts_after_lease_expiry_and_restart(tmp_path):
    path = tmp_path / "access.sqlite"
    original = SQLitePublicDocumentAccess(path)
    await original.remember_robots(
        "news.example", "User-agent: *\nDisallow:", 60, now=900
    )
    claim = await original.claim("news.example", now=1000, lease_seconds=20)
    assert claim.token
    restarted = SQLitePublicDocumentAccess(path)
    too_soon = await restarted.claim("news.example", now=1020, lease_seconds=20)
    assert too_soon.token is None and too_soon.retry_after_seconds == 40
    assert (await restarted.claim("news.example", now=1060, lease_seconds=20)).token


async def test_stale_finish_cannot_release_a_new_owners_lease(tmp_path):
    access = SQLitePublicDocumentAccess(tmp_path / "access.sqlite")
    old = await access.claim("news.example", now=1000, lease_seconds=20)
    new = await access.claim("news.example", now=1021, lease_seconds=20)
    assert old.token and new.token and old.token != new.token
    await access.finish("news.example", old.token, now=1022)
    blocked = await access.claim("news.example", now=1022, lease_seconds=20)
    assert blocked.token is None and blocked.retry_after_seconds == 19
    await access.finish("news.example", new.token, now=1023)
    assert (await access.claim("news.example", now=1023, lease_seconds=20)).token


async def test_cache_eviction_and_expiry_do_not_erase_publisher_timing(tmp_path):
    access = SQLitePublicDocumentAccess(tmp_path / "access.sqlite", cache_entries=1)
    await access.remember_robots("first.example", "first", 600, now=1000)
    claim = await access.claim("first.example", now=1000, lease_seconds=20)
    assert claim.token
    await access.finish("first.example", claim.token, now=1001)
    await access.remember_robots("second.example", "second", 0, now=1002)
    assert await access.robots("first.example", now=1003) is None
    assert await access.robots("second.example", now=1003) == "second"
    blocked = await access.claim("first.example", now=1100, lease_seconds=20)
    assert blocked.token is None and blocked.retry_after_seconds == 501
    assert await access.robots("second.example", now=4602) is None


@pytest.mark.parametrize("interval", [-1, float("inf"), float("nan"), 31_536_001])
async def test_invalid_policy_intervals_never_enter_durable_state(tmp_path, interval):
    access = SQLitePublicDocumentAccess(tmp_path / "access.sqlite")
    with pytest.raises(ValueError):
        await access.remember_robots("news.example", "rules", interval, now=1000)
    assert await access.robots("news.example", now=1000) is None
