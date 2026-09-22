"""Persistence seam for isolated planning and replay workspaces."""

from typing import Protocol

from disaster_monitor.domain.planning import PlanningWorkspace


class PlanningWorkspaceStore(Protocol):
    async def put(self, workspace: PlanningWorkspace) -> None: ...

    async def get(self, workspace_id: str) -> PlanningWorkspace | None: ...

    async def list(self) -> tuple[PlanningWorkspace, ...]: ...


__all__ = ["PlanningWorkspaceStore"]
