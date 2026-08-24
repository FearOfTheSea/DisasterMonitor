"""Port for bounded structured specialist analysis over admitted projections."""

from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.application.agent.models import SpecialistArtifactProjection
from disaster_monitor.domain.coordination import (
    SpecialistFindingDraft,
    SpecialistHandoff,
)
from disaster_monitor.domain.memory import MemoryContextArtifact


class SpecialistModelError(Exception):
    """Safe failure for malformed or authority-seeking specialist output."""


@dataclass(frozen=True, slots=True)
class SpecialistModelRequest:
    handoff: SpecialistHandoff
    artifact: SpecialistArtifactProjection
    safety_policy_fingerprint: str
    memory_context: MemoryContextArtifact | None = None
    tools: tuple[str, ...] = ()
    provider_authority: bool = False
    recursive_agent_authority: bool = False

    def __post_init__(self) -> None:
        if self.tools or self.provider_authority or self.recursive_agent_authority:
            raise ValueError(
                "Specialist model requests cannot carry external authority."
            )


class SpecialistModel(Protocol):
    async def generate_finding(
        self, request: SpecialistModelRequest
    ) -> SpecialistFindingDraft: ...
