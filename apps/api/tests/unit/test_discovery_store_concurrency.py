"""Windows readers must not make a scan's terminal replacement fail."""

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from disaster_monitor.domain.discovery import DiscoveryRun, ReportingInterval
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
async def test_terminal_scan_write_survives_an_active_reader(tmp_path, monkeypatch):
    run = DiscoveryRun(str(uuid4()), ReportingInterval.at_start(7, datetime.now(UTC)))
    store = FileDiscoveryStore(tmp_path)
    await store.save(run)
    opened, release = Event(), Event()
    original = Path.read_bytes
    target = tmp_path / f"{run.scan_id}.json"

    def held_read(path):
        if path != target or opened.is_set():
            return original(path)
        with path.open("rb") as reader:
            opened.set()
            assert release.wait(3)
            return reader.read()

    monkeypatch.setattr(Path, "read_bytes", held_read)
    reading = asyncio.create_task(store.read(run.scan_id))
    assert await asyncio.to_thread(opened.wait, 3)
    writing = asyncio.create_task(store.save(replace(run, status="completed")))
    try:
        await asyncio.sleep(0.05)
    finally:
        release.set()
    await asyncio.gather(reading, writing)
    assert (await store.read(run.scan_id)).status == "completed"
