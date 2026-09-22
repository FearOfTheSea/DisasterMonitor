"""In-process planning workspace persistence for local deployments."""

from disaster_monitor.application.ports.planning import PlanningWorkspaceStore
from disaster_monitor.domain.planning import PlanningWorkspace


class InMemoryPlanningWorkspaceStore(PlanningWorkspaceStore):
    def __init__(self) -> None:
        self._items: dict[str, PlanningWorkspace] = {}

    async def put(self, workspace: PlanningWorkspace) -> None:
        self._items.setdefault(workspace.workspace_id, workspace)

    async def get(self, workspace_id: str) -> PlanningWorkspace | None:
        return self._items.get(workspace_id)

    async def list(self) -> tuple[PlanningWorkspace, ...]:
        return tuple(self._items.values())


__all__ = ["InMemoryPlanningWorkspaceStore"]
