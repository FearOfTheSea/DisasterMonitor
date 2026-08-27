"""Bounded typed contracts shared by coherent agent-tool capabilities."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.application.agent.models import (
    AgentExecutionState,
    InvestigationAction,
)

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


async def execute_plan(state: AgentExecutionState, registry: ToolRegistry) -> None:
    """Execute a validated plan with strict sequencing and call budgets."""
    completed = set(state.completed_steps)
    state.pending_steps = [step.step_id for step in state.plan.steps]
    for step in state.plan.steps:
        if state.tool_call_count >= MAX_TOOL_CALLS:
            raise RuntimeError("The agent tool-call budget was exhausted.")
        if any(dependency not in completed for dependency in step.dependencies):
            raise ValueError("An agent tool prerequisite was not completed.")
        tool = registry.resolve(step.tool_name)
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
        else:
            action = await tool.execute(state)
        state.tool_call_count += 1
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
