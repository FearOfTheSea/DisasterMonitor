"""Atomic bounded local storage for identity registry metadata."""

import asyncio
from pathlib import Path

from disaster_monitor.infrastructure.private_files import (
    atomic_private_write,
    restrict_private_path,
    verify_private_path,
)


class FileIncidentIdentityStore:
    def __init__(self, path: Path, *, maximum_bytes: int = 32 * 1024 * 1024):
        self._path, self._maximum_bytes = path.resolve(), maximum_bytes
        if self._path.is_file() and not verify_private_path(self._path):
            restrict_private_path(self._path, backup=True)

    def read(self) -> str | None:
        if not self._path.is_file():
            return None
        if self._path.stat().st_size > self._maximum_bytes:
            raise ValueError("Incident identity metadata exceeds its byte bound.")
        return self._path.read_text(encoding="utf-8")

    async def write(self, content: str) -> None:
        if len(content.encode("utf-8")) > self._maximum_bytes:
            raise ValueError("Incident identity metadata exceeds its byte bound.")
        await asyncio.to_thread(atomic_private_write, self._path, content)
