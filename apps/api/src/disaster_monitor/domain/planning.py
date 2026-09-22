"""Structurally isolated hypothetical scenario and replay workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")


class WorkspaceKind(StrEnum):
    PLANNING_SCENARIO = "planning_scenario"
    HISTORICAL_REPLAY = "historical_replay"


class WorkspaceTarget(StrEnum):
    SIMULATION_STATE = "simulation_state"
    CANONICAL_EVIDENCE = "canonical_evidence"


@dataclass(frozen=True, slots=True)
class PlanningLayer:
    layer_id: str
    title: str
    source_reference: str
    sha256: str
    role: str = "hypothetical_scenario_layer"

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.layer_id, self.title, self.source_reference)
        ):
            raise ValueError("Planning layers require identity and source reference.")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("Planning layer checksums must be lowercase SHA-256.")
        if self.role != "hypothetical_scenario_layer":
            raise ValueError("Planning layers must remain hypothetical.")


@dataclass(frozen=True, slots=True)
class PlanningWorkspace:
    workspace_id: str
    kind: WorkspaceKind
    title: str
    created_by: str
    created_at: datetime
    source_snapshot_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    layers: tuple[PlanningLayer, ...]
    replay_started_at: datetime | None = None
    simulated: bool = True
    can_write_canonical_evidence: bool = False

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.workspace_id, self.title, self.created_by)
        ):
            raise ValueError("Planning workspaces require identity and attribution.")
        _require_aware("created_at", self.created_at)
        if not self.source_snapshot_ids or any(
            not value.strip() for value in self.source_snapshot_ids
        ):
            raise ValueError("Planning workspaces require pinned source snapshots.")
        if any(not value.strip() for value in self.assumptions):
            raise ValueError("Planning assumptions must not be empty.")
        if self.kind is WorkspaceKind.HISTORICAL_REPLAY:
            if self.replay_started_at is None:
                raise ValueError("Historical replay requires a simulated start time.")
            _require_aware("replay_started_at", self.replay_started_at)
        elif self.replay_started_at is not None:
            raise ValueError("Only replay workspaces have a replay start time.")
        if not self.simulated or self.can_write_canonical_evidence:
            raise ValueError("Simulated workspaces must remain isolated from evidence.")


__all__ = [
    "PlanningLayer",
    "PlanningWorkspace",
    "WorkspaceKind",
    "WorkspaceTarget",
]
