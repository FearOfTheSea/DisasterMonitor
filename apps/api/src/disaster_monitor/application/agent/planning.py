"""Deterministic bounded planning and plan validation."""

from uuid import NAMESPACE_URL, uuid5

from disaster_monitor.application.agent.models import (
    InvestigationPlan,
    PlanStep,
    ValidatedDisasterTask,
)

DEFAULT_TOOL_ORDER = (
    "list_sources_for_task",
    "find_disaster_event",
    "retrieve_situation_evidence",
    "reconcile_disaster_evidence",
    "compose_disaster_answer",
)

_BUILTIN_TOOL_PREREQUISITES = {
    "list_sources_for_task": (),
    "find_disaster_event": ("list_sources_for_task",),
    "retrieve_situation_evidence": ("find_disaster_event",),
    "reconcile_disaster_evidence": ("retrieve_situation_evidence",),
    "compose_disaster_answer": ("reconcile_disaster_evidence",),
}


def default_investigation_plan(task: ValidatedDisasterTask) -> InvestigationPlan:
    plan_id = str(uuid5(NAMESPACE_URL, f"disaster-monitor:{task.question}"))
    purposes = (
        "List suitable maintained sources and coverage gaps.",
        "Find and resolve the requested disaster event.",
        "Retrieve event-correlated situation evidence.",
        "Reconcile normalized evidence and preserve conflicts.",
        "Compose the requested evidence-backed answer.",
    )
    steps = tuple(
        PlanStep(
            step_id=f"step-{index}",
            tool_name=name,
            arguments=(),
            purpose=purposes[index - 1],
            dependencies=() if index == 1 else (f"step-{index - 1}",),
        )
        for index, name in enumerate(DEFAULT_TOOL_ORDER, start=1)
    )
    gaps = []
    if any(item.value == "images" for item in task.output_modalities):
        gaps.append("Trusted disaster-image retrieval is not implemented.")
    if any(item.value == "map" for item in task.output_modalities):
        gaps.append("Agent-controlled map layers are not implemented.")
    return InvestigationPlan(plan_id, task.question, steps, capability_gaps=tuple(gaps))


def validate_plan(
    plan: InvestigationPlan, *, allowed_tools: frozenset[str]
) -> InvestigationPlan:
    if not plan.steps or len(plan.steps) > min(plan.maximum_steps, 8):
        raise ValueError("The investigation plan has an invalid step count.")
    seen_steps: set[str] = set()
    seen_tools: set[str] = set()
    for step in plan.steps:
        if step.step_id in seen_steps:
            raise ValueError("The investigation plan has duplicate step IDs.")
        if step.tool_name not in allowed_tools:
            raise ValueError(f"Unknown agent tool: {step.tool_name}")
        if any(dependency not in seen_steps for dependency in step.dependencies):
            raise ValueError("The investigation plan has invalid sequencing.")
        required_tools = _BUILTIN_TOOL_PREREQUISITES.get(step.tool_name, ())
        if any(required_tool not in seen_tools for required_tool in required_tools):
            raise ValueError(
                "The investigation plan has invalid sequencing for trusted "
                "disaster tools."
            )
        if step.arguments:
            raise ValueError(
                "Model-provided tool arguments are not accepted in phase 3."
            )
        seen_steps.add(step.step_id)
        seen_tools.add(step.tool_name)
    if (
        seen_tools.intersection(_BUILTIN_TOOL_PREREQUISITES)
        and "compose_disaster_answer" not in seen_tools
    ):
        raise ValueError(
            "The investigation plan has invalid sequencing; trusted disaster plans "
            "must compose a grounded answer."
        )
    return plan
