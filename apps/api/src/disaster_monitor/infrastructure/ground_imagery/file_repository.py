"""Bounded atomic local request metadata, alongside immutable imagery artifacts."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from disaster_monitor.application.ground_imagery.models import (
    GroundImageryRequest,
    GroundImageryRequestState,
)
from disaster_monitor.application.ports.ground_imagery.repository_codec import (
    request_from_document,
    request_to_document,
)
from disaster_monitor.infrastructure.ground_imagery.memory_repository import (
    InMemoryGroundImageryRequestStore,
)
from disaster_monitor.infrastructure.private_files import (
    atomic_private_write,
    restrict_private_path,
    verify_private_path,
)


class FileGroundImageryRequestStore(InMemoryGroundImageryRequestStore):
    durable = True

    def __init__(
        self,
        path: Path,
        *,
        maximum_records: int = 256,
        maximum_bytes: int = 64 * 1024 * 1024,
    ):
        super().__init__()
        self._path = path.resolve()
        self._maximum_records = maximum_records
        self._maximum_bytes = maximum_bytes
        self._write_lock = asyncio.Lock()
        if self._path.exists():
            if self._path.stat().st_size > maximum_bytes:
                raise ValueError("Ground request metadata exceeds its memory bound.")
            if not verify_private_path(self._path):
                restrict_private_path(self._path, backup=True)
            document = json.loads(self._path.read_text(encoding="utf-8"))
            if document.get("version") != 1:
                raise ValueError("Unsupported Ground request metadata version.")
            interrupted = False
            for raw in document["requests"]:
                request = request_from_document(raw)
                if request.state in (
                    GroundImageryRequestState.QUEUED,
                    GroundImageryRequestState.RESOLVING,
                    GroundImageryRequestState.SEARCHING,
                    GroundImageryRequestState.ASSESSING,
                ):
                    request = replace(
                        request,
                        state=GroundImageryRequestState.FAILED,
                        reason_codes=(*request.reason_codes, "interrupted_restart"),
                        request_version=request.request_version + 1,
                        updated_at=max(datetime.now(UTC), request.updated_at),
                    )
                    interrupted = True
                self.requests[request.request_id] = request
            if len(self.requests) > maximum_records:
                raise ValueError("Ground request metadata exceeds its record bound.")
            if interrupted:
                self._persist(self.requests)

    async def save_request(self, request: GroundImageryRequest) -> None:
        async with self._write_lock:
            current = self.requests.get(request.request_id)
            if current and current.request_version > request.request_version:
                return
            records = {**self.requests, request.request_id: request}
            ordered = sorted(
                records.values(),
                key=lambda item: (item.updated_at, item.request_id),
                reverse=True,
            )
            records = {
                item.request_id: item for item in ordered[: self._maximum_records]
            }
            await asyncio.to_thread(self._persist, records)
            self.requests = records

    def _persist(self, records: dict[str, GroundImageryRequest]) -> None:
        content = json.dumps(
            {
                "version": 1,
                "requests": [request_to_document(item) for item in records.values()],
            },
            separators=(",", ":"),
        )
        if len(content.encode("utf-8")) > self._maximum_bytes:
            raise ValueError("Ground request metadata exceeds its byte bound.")
        atomic_private_write(self._path, content)

    async def claim_due_watch(self, *, now: datetime) -> str | None:
        # File durability alone does not supply a scheduler or distributed lease.
        return None
