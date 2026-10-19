"""Atomic, bounded local scan persistence; never deserialize executable objects."""

import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter

from disaster_monitor.domain.discovery import DiscoveryRun

_CODEC = TypeAdapter(DiscoveryRun)


class FileDiscoveryStore:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = asyncio.Lock()

    def _path(self, scan_id: str) -> Path:
        return self._root / f"{UUID(scan_id)}.json"

    async def save(self, run: DiscoveryRun) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save, run)

    def _save(self, run: DiscoveryRun) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._path(run.scan_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(_CODEC.dump_json(run))
        temporary.replace(path)
        # Never remove running work. Retain the latest eight finished scans.
        finished = []
        sources = {}
        for entry in self._root.glob("*.json"):
            retained = _CODEC.validate_json(entry.read_bytes())
            if retained.status != "running":
                finished.append(entry)
                sources[retained.scan_id] = retained.reprocessed_from
        ordered = sorted(finished, key=lambda p: p.stat().st_mtime, reverse=True)
        keep = {entry.stem for entry in ordered[:8]}
        # A derived result must not evict the original acquisition it references.
        # Reprocessing always points at the original, so no unbounded chain grows.
        keep.update(
            source for identifier in tuple(keep) if (source := sources[identifier])
        )
        for entry in ordered[8:]:
            if entry.stem not in keep:
                entry.unlink()

    async def read(self, scan_id: str) -> DiscoveryRun | None:
        path = self._path(scan_id)
        # Windows denies replacement/deletion while a normal reader holds the
        # destination open. Share the writer lock through the complete file read.
        async with self._lock:
            try:
                content = await asyncio.to_thread(path.read_bytes)
            except FileNotFoundError:
                return None
        return _CODEC.validate_json(content)

    async def recent(self) -> tuple[DiscoveryRun, ...]:
        if not self._root.exists():
            return ()
        runs = []
        for path in self._root.glob("*.json"):
            run = await self.read(path.stem)
            if run:
                runs.append(run)
        return tuple(sorted(runs, key=lambda r: r.interval.end, reverse=True))

    async def recover(self) -> None:
        for run in await self.recent():
            if run.status == "running":
                await self.save(
                    replace(
                        run,
                        status="incomplete",
                        issues=(
                            *run.issues,
                            "Scan interrupted by backend restart; "
                            "retained results available.",
                        ),
                    )
                )
