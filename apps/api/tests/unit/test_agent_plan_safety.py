import pytest

from disaster_monitor.application.agent.models import (
    AgentReview,
    DisasterTaskDraft,
    InvestigationPlan,
    PlanStep,
    ReviewDecision,
)
from disaster_monitor.application.agent.planning import (
    DEFAULT_TOOL_ORDER,
    default_investigation_plan,
    validate_plan,
)
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.agent.tooling import ToolDescription, ToolRegistry
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


class NoopTool:
    def __init__(self, name: str) -> None:
        self.description = ToolDescription(name, "test tool", (), (), (), (), False)

    async def execute(self, state) -> str:
        return f"ran {self.description.name}"


class ComposeOnlyAgent:
    async def interpret(self, question):
        return DisasterTaskDraft(
            True,
            True,
            ("earthquake",),
            ("Japan",),
            information_needs=("event_overview",),
            output_modalities=("text",),
        )

    async def propose_plan(self, task, tool_descriptions):
        return InvestigationPlan(
            "unsafe",
            task.question,
            (
                PlanStep(
                    "compose",
                    "compose_disaster_answer",
                    (),
                    "Answer immediately.",
                ),
            ),
        )

    async def review_progress(self, task, completed_steps):
        return AgentReview(ReviewDecision.FINISH)


def _step(index: int, name: str) -> PlanStep:
    return PlanStep(
        f"step-{index}",
        name,
        (),
        name,
        () if index == 1 else (f"step-{index - 1}",),
    )


def test_plan_validation_requires_complete_trusted_disaster_pipeline() -> None:
    allowed = frozenset(DEFAULT_TOOL_ORDER)
    compose_only = InvestigationPlan(
        "unsafe",
        "compose without verification",
        (_step(1, "compose_disaster_answer"),),
    )
    missing_composer = InvestigationPlan(
        "incomplete",
        "retrieve but never compose",
        tuple(
            _step(index, name)
            for index, name in enumerate(DEFAULT_TOOL_ORDER[:-1], 1)
        ),
    )
    valid = InvestigationPlan(
        "valid",
        "trusted workflow",
        tuple(_step(index, name) for index, name in enumerate(DEFAULT_TOOL_ORDER, 1)),
    )

    with pytest.raises(ValueError, match="sequencing"):
        validate_plan(compose_only, allowed_tools=allowed)
    with pytest.raises(ValueError, match="compose"):
        validate_plan(missing_composer, allowed_tools=allowed)
    assert validate_plan(valid, allowed_tools=allowed) == valid


@pytest.mark.asyncio
async def test_runtime_falls_back_when_model_skips_required_disaster_tools() -> None:
    catalog = StaticCountryCatalog()
    tools = ToolRegistry(tuple(NoopTool(name) for name in DEFAULT_TOOL_ORDER))
    runtime = DisasterAgentRuntime(
        country_catalog=catalog,
        query_parser=DisasterQueryParser(catalog),
        tool_registry=tools,
        agent_model=ComposeOnlyAgent(),
    )

    state = await runtime.run("Give me the latest earthquake information in Japan.")

    assert state.plan == default_investigation_plan(state.task)
    assert tuple(step.tool_name for step in state.plan.steps) == DEFAULT_TOOL_ORDER
    assert state.tool_call_count == len(DEFAULT_TOOL_ORDER)
