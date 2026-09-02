"""Port for bounded agent interpretation and planning."""

from typing import Protocol

from disaster_monitor.application.agent.models import (
    AgentReview,
    DisasterTaskDraft,
    InvestigationPlan,
    ValidatedDisasterTask,
)
from disaster_monitor.application.agent.sufficiency import (
    EvidenceSufficiencyAssessment,
)
from disaster_monitor.application.disaster import DisasterReport


class AgentModelError(Exception):
    """Safe typed failure returned after structured output cannot be validated."""


class AgentModel(Protocol):
    async def interpret(self, question: str) -> DisasterTaskDraft: ...

    async def localize_grounded_response(
        self, report: DisasterReport, language: str
    ) -> str: ...

    async def propose_plan(
        self, task: ValidatedDisasterTask, tool_descriptions: tuple[str, ...]
    ) -> InvestigationPlan: ...

    async def review_progress(
        self,
        task: ValidatedDisasterTask,
        assessment: EvidenceSufficiencyAssessment,
    ) -> AgentReview: ...
