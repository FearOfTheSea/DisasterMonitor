"""Execute a bounded disaster report through the shared investigation tools."""

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InformationNeed,
    OutputModality,
    TaskKind,
    ValidatedDisasterTask,
)
from disaster_monitor.application.agent.planning import default_investigation_plan
from disaster_monitor.application.agent.tooling import ToolRegistry, execute_plan
from disaster_monitor.application.disaster import DisasterQuery, DisasterReport


class DisasterInvestigationWorkflow:
    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools

    async def execute(self, query: DisasterQuery) -> DisasterReport:
        task = ValidatedDisasterTask(
            question=(
                f"Current {query.disaster.value} information in "
                f"{query.country.canonical_name}"
            ),
            kind=TaskKind.INVESTIGATION,
            requires_evidence=True,
            disaster=query.disaster,
            country=query.country,
            date_from=query.date_from,
            date_to=query.date_to,
            information_needs=(InformationNeed.EVENT_OVERVIEW,),
            output_modalities=(OutputModality.TEXT,),
            query=query,
        )
        plan = default_investigation_plan(task)
        state = AgentExecutionState(task, plan)
        state.capability_gaps.extend(plan.capability_gaps)
        await execute_plan(state, self._tools)
        if state.workspace.report is None:
            raise RuntimeError("The shared disaster tool workflow produced no report.")
        return state.workspace.report
