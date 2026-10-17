import pytest

from disaster_monitor.application.operator_workspace.service import (
    OperatorWorkspaceService,
)
from disaster_monitor.infrastructure.operator_workspace.memory_store import (
    InMemoryOperatorWorkspaceStore,
)


@pytest.mark.asyncio
async def test_generic_workspace_aggregates_bookmarks_and_explicit_scope_filters():
    service = OperatorWorkspaceService(InMemoryOperatorWorkspaceStore())
    for scope in (None, "incident-a", "incident-b"):
        await service.add_bookmark(
            incident_id=scope,
            target_type="incident",
            target_id=str(scope),
            label=str(scope),
        )
    generic = await service.export_state(incident_id=None)
    assert len(generic["bookmarks"]) == 3
    scoped = await service.export_state(incident_id="incident-a")
    assert len(scoped["bookmarks"]) == 1
    explicit_global = await service.export_state(
        incident_id=None, aggregate_bookmarks=False
    )
    assert len(explicit_global["bookmarks"]) == 1
