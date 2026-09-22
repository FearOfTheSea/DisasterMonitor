"""Create workspaces whose state cannot enter live evidence."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from disaster_monitor.application.ports.planning import PlanningWorkspaceStore
from disaster_monitor.domain.planning import (
    PlanningLayer,
    PlanningWorkspace,
    WorkspaceKind,
    WorkspaceTarget,
)


class PlanningWorkspaceService:
    def __init__(
        self,
        store: PlanningWorkspaceStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._clock = clock

    async def create_scenario(
        self,
        *,
        title: str,
        created_by: str,
        source_snapshot_ids: tuple[str, ...],
        assumptions: tuple[str, ...],
        layers: tuple[PlanningLayer, ...],
    ) -> PlanningWorkspace:
        return await self._create(
            kind=WorkspaceKind.PLANNING_SCENARIO,
            title=title,
            created_by=created_by,
            source_snapshot_ids=source_snapshot_ids,
            assumptions=assumptions,
            layers=layers,
            replay_started_at=None,
        )

    async def create_replay(
        self,
        *,
        title: str,
        created_by: str,
        source_snapshot_ids: tuple[str, ...],
        replay_started_at: datetime,
    ) -> PlanningWorkspace:
        return await self._create(
            kind=WorkspaceKind.HISTORICAL_REPLAY,
            title=title,
            created_by=created_by,
            source_snapshot_ids=source_snapshot_ids,
            assumptions=(),
            layers=(),
            replay_started_at=replay_started_at,
        )

    async def assert_write_allowed(
        self, workspace_id: str, target: WorkspaceTarget
    ) -> None:
        workspace = await self._store.get(workspace_id)
        if workspace is None:
            raise LookupError(workspace_id)
        if target is WorkspaceTarget.CANONICAL_EVIDENCE:
            raise ValueError(
                "Simulated workspaces cannot write to canonical evidence state."
            )

    async def _create(
        self,
        *,
        kind: WorkspaceKind,
        title: str,
        created_by: str,
        source_snapshot_ids: tuple[str, ...],
        assumptions: tuple[str, ...],
        layers: tuple[PlanningLayer, ...],
        replay_started_at: datetime | None,
    ) -> PlanningWorkspace:
        created_at = self._clock()
        material = "|".join(
            (
                kind.value,
                title.strip(),
                created_by.strip(),
                created_at.isoformat(),
                *source_snapshot_ids,
            )
        )
        workspace = PlanningWorkspace(
            workspace_id=(
                f"planning-workspace:{sha256(material.encode()).hexdigest()[:24]}"
            ),
            kind=kind,
            title=title.strip(),
            created_by=created_by.strip(),
            created_at=created_at,
            source_snapshot_ids=tuple(dict.fromkeys(source_snapshot_ids)),
            assumptions=assumptions,
            layers=layers,
            replay_started_at=replay_started_at,
        )
        await self._store.put(workspace)
        return workspace


__all__ = ["PlanningWorkspaceService"]
