"""Bounded typed contracts shared by coherent agent-tool capabilities."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InvestigationAction,
    InvestigationPlan,
)
from disaster_monitor.application.agent.trace import TraceEventKind

MAX_TOOL_CALLS = 12


@dataclass(frozen=True, slots=True)
class ToolDescription:
    name: str
    description: str
    required_state: tuple[str, ...]
    accepted_arguments: tuple[str, ...]
    produced_artifacts: tuple[str, ...]
    supported_information_roles: tuple[str, ...]
    performs_live_io: bool

    def planning_text(self) -> str:
        return f"{self.name}: {self.description}"


class AgentTool(Protocol):
    description: ToolDescription

    async def execute(self, state: AgentExecutionState) -> str: ...


class ToolRegistry:
    """Immutable allowlist of explicitly constructed agent tools."""

    def __init__(self, tools: Iterable[AgentTool]) -> None:
        resolved = tuple(tools)
        names = [tool.description.name for tool in resolved]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate agent tool name.")
        self._tools = {tool.description.name: tool for tool in resolved}
        self._descriptions = tuple(tool.description for tool in resolved)

    @property
    def descriptions(self) -> tuple[ToolDescription, ...]:
        return self._descriptions

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def resolve(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise ValueError(f"Unknown agent tool: {name}") from error


async def execute_plan(
    state: AgentExecutionState,
    registry: ToolRegistry,
    *,
    plan: InvestigationPlan | None = None,
    step_ids: tuple[str, ...] | None = None,
    stop_before_composition: bool = False,
    trace_phase: str = "direct",
) -> None:
    """Execute a validated plan with strict sequencing and call budgets.

    The optional controls are used by Runtime v2 to execute the validated
    pre-composition prefix and an application-generated follow-up. The default
    remains the legacy whole-plan behavior.
    """
    execution_plan = plan or state.plan
    selected_step_ids = set(step_ids) if step_ids is not None else None
    completed = set(state.completed_steps)
    state.pending_steps = [
        step.step_id
        for step in execution_plan.steps
        if selected_step_ids is None or step.step_id in selected_step_ids
    ]
    for step in execution_plan.steps:
        if selected_step_ids is not None and step.step_id not in selected_step_ids:
            continue
        if stop_before_composition and step.tool_name == "compose_disaster_answer":
            break
        if state.tool_call_count >= MAX_TOOL_CALLS:
            state.trace.record(
                TraceEventKind.BUDGET_VIOLATION,
                budget="tool_call",
                phase=trace_phase,
            )
            raise RuntimeError("The agent tool-call budget was exhausted.")
        if any(dependency not in completed for dependency in step.dependencies):
            state.trace.record(
                TraceEventKind.TOOL_FAILED,
                phase=trace_phase,
                step_id=step.step_id,
                tool=step.tool_name,
                failure="prerequisite",
            )
            raise ValueError("An agent tool prerequisite was not completed.")
        try:
            tool = registry.resolve(step.tool_name)
        except Exception:
            state.trace.record(
                TraceEventKind.TOOL_FAILED,
                phase=trace_phase,
                step_id=step.step_id,
                tool=step.tool_name,
                failure="unknown_tool",
            )
            raise
        state.tool_call_count += 1
        if state.workspace.selected_event is None and step.tool_name in {
            "retrieve_situation_evidence",
            "reconcile_disaster_evidence",
            "analyze_multimodal_assets",
            "build_common_operational_picture",
        }:
            action = (
                f"Skipped step {step.step_id} ({step.purpose}): no selected event "
                "was available."
            )
            state.trace.record(
                TraceEventKind.TOOL_SKIPPED,
                phase=trace_phase,
                step_id=step.step_id,
                tool=step.tool_name,
            )
        else:
            try:
                action = await tool.execute(state)
            except Exception:
                state.trace.record(
                    TraceEventKind.TOOL_FAILED,
                    phase=trace_phase,
                    step_id=step.step_id,
                    tool=step.tool_name,
                    failure="execution_error",
                )
                raise
            state.trace.record(
                TraceEventKind.TOOL_COMPLETED,
                phase=trace_phase,
                step_id=step.step_id,
                tool=step.tool_name,
            )
        state.completed_steps.append(step.step_id)
        completed.add(step.step_id)
        state.pending_steps.remove(step.step_id)
        state.actions.append(InvestigationAction(step.step_id, action))


__all__ = [
    "AgentTool",
    "MAX_TOOL_CALLS",
    "ToolDescription",
    "ToolRegistry",
    "execute_plan",
]
