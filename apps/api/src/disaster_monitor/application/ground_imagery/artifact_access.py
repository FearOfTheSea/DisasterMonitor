"""Read, retain, and expose the provenance of published Ground artifacts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from disaster_monitor.application.ground_imagery.artifact_workflow import (
    GroundImageryArtifactWorkflow,
)
from disaster_monitor.application.ground_imagery.errors import (
    GroundImageryRequestNotFound,
)
from disaster_monitor.application.ground_imagery.manifest import (
    build_manifest,
    request_has_selection,
)
from disaster_monitor.application.ground_imagery.models import GroundImageryRequest
from disaster_monitor.application.ground_imagery.request_indexes import (
    GroundImageryRequestIndexes,
)
from disaster_monitor.application.ports.ground_imagery.artifacts import StoredArtifact
from disaster_monitor.application.ports.ground_imagery.repository import (
    GroundImageryRequestStore,
)


class GroundImageryArtifactAccess:
    """Own artifact reads, retention cleanup, and credential-free manifests."""

    def __init__(
        self,
        workflow: GroundImageryArtifactWorkflow,
        store: GroundImageryRequestStore,
        indexes: GroundImageryRequestIndexes,
        clock: Callable[[], datetime],
    ) -> None:
        self._workflow = workflow
        self._store = store
        self._indexes = indexes
        self._clock = clock

    async def cleanup_artifacts(
        self, *, retention_days: int, now: datetime | None = None
    ) -> tuple[str, ...]:
        if retention_days < 1:
            raise ValueError("Ground artifact retention must be positive.")
        requests = await self._store.list_requests()
        referenced = frozenset(
            artifact.artifact_id
            for request in requests
            for artifact in request.artifacts
        )
        return await self._workflow.delete_unreferenced(
            referenced_artifact_ids=referenced,
            older_than=(now or self._clock()) - timedelta(days=retention_days),
        )

    async def read_artifact(
        self, artifact_id: str
    ) -> tuple[StoredArtifact, bytes] | None:
        return await self._workflow.read_artifact(artifact_id)

    async def render_tile(self, artifact_id: str, zoom: int, x: int, y: int) -> bytes:
        return await self._workflow.render_tile(artifact_id, zoom, x, y)

    def readiness(self) -> dict[str, object]:
        return self._workflow.readiness()

    async def manifest(self, request_id: str) -> dict[str, object]:
        return build_manifest(await self._request(request_id))

    async def manifest_for_selection(
        self, selection_id_value: str
    ) -> dict[str, object]:
        request_id = self._indexes.request_for_selection(selection_id_value)
        request = (
            None if request_id is None else await self._store.get_request(request_id)
        )
        if request is None:
            request = await self._store.get_request_for_selection(selection_id_value)
        if request is None:
            raise GroundImageryRequestNotFound(
                "The imagery selection manifest was not found."
            )
        if not any(
            item.selection_id == selection_id_value for item in request.artifacts
        ) and not request_has_selection(request, selection_id_value):
            raise GroundImageryRequestNotFound(
                "The imagery selection manifest was not found."
            )
        return build_manifest(request)

    async def aclose(self) -> None:
        await self._workflow.aclose()

    async def _request(self, request_id: str) -> GroundImageryRequest:
        request = await self._store.get_request(request_id)
        if request is None:
            raise GroundImageryRequestNotFound("The imagery request was not found.")
        return request


__all__ = ["GroundImageryArtifactAccess"]
