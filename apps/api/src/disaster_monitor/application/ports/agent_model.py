"""Port for bounded agent interpretation and planning."""

from typing import Protocol

from disaster_monitor.application.agent.models import (
    AgentReview,
    DisasterTaskDraft,
    InvestigationPlan,
    ValidatedDisasterTask,
)


class AgentModelError(Exception):
    """Safe typed failure returned after structured output cannot be validated."""


class AgentModel(Protocol):
    async def interpret(self, question: str) -> DisasterTaskDraft: ...

    async def propose_plan(
        self, task: ValidatedDisasterTask, tool_descriptions: tuple[str, ...]
    ) -> InvestigationPlan: ...

    async def review_progress(
        self, task: ValidatedDisasterTask, completed_steps: tuple[str, ...]
    ) -> AgentReview: ...
