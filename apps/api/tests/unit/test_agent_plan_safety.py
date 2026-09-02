import pytest

from disaster_monitor.application.agent.models import InvestigationPlan, PlanStep
from disaster_monitor.application.agent.planning import (
    DEFAULT_TOOL_ORDER,
    MULTIMODAL_TOOL_ORDER,
    validate_plan,
)


def test_plan_validation_rejects_incomplete_trusted_disaster_pipeline() -> None:
    allowed = frozenset(DEFAULT_TOOL_ORDER)
    compose_only = InvestigationPlan(
        "unsafe",
        "compose without verification",
        (
            PlanStep(
                "compose",
                "compose_disaster_answer",
                (),
                "Answer immediately.",
            ),
        ),
    )
    missing_composer = InvestigationPlan(
        "incomplete",
        "retrieve but never compose",
        tuple(
            PlanStep(
                f"step-{index}",
                name,
                (),
                name,
                () if index == 1 else (f"step-{index - 1}",),
            )
            for index, name in enumerate(DEFAULT_TOOL_ORDER[:-1], 1)
        ),
    )

    with pytest.raises(ValueError, match="sequencing"):
        validate_plan(compose_only, allowed_tools=allowed)
    with pytest.raises(ValueError, match="compose"):
        validate_plan(missing_composer, allowed_tools=allowed)


def test_plan_validation_rejects_duplicate_trusted_tool_steps() -> None:
    tools = (*DEFAULT_TOOL_ORDER, DEFAULT_TOOL_ORDER[-1])
    plan = InvestigationPlan(
        "duplicate-composition",
        "Do not repeat a trusted workflow stage.",
        tuple(
            PlanStep(
                f"step-{index}",
                name,
                (),
                name,
                () if index == 1 else (f"step-{index - 1}",),
            )
            for index, name in enumerate(tools, 1)
        ),
    )

    with pytest.raises(ValueError, match="duplicate trusted"):
        validate_plan(plan, allowed_tools=frozenset(DEFAULT_TOOL_ORDER))


def test_plan_validation_rejects_composition_that_is_not_final() -> None:
    plan = InvestigationPlan(
        "late-composition",
        "Composition is a terminal operation.",
        tuple(
            PlanStep(
                f"step-{index}",
                name,
                (),
                name,
                () if index == 1 else (f"step-{index - 1}",),
            )
            for index, name in enumerate((*DEFAULT_TOOL_ORDER, "dummy"), 1)
        ),
    )

    with pytest.raises(ValueError, match="final"):
        validate_plan(
            plan,
            allowed_tools=frozenset((*DEFAULT_TOOL_ORDER, "dummy")),
            require_composition=True,
        )


def test_plan_validation_rejects_multimodal_tools_without_admitted_assets() -> None:
    tool_order = (
        *DEFAULT_TOOL_ORDER[:-1],
        *MULTIMODAL_TOOL_ORDER,
        DEFAULT_TOOL_ORDER[-1],
    )
    plan = InvestigationPlan(
        "unsupported-multimodal-plan",
        "Do not infer assets.",
        tuple(
            PlanStep(
                f"step-{index}",
                name,
                (),
                name,
                () if index == 1 else (f"step-{index - 1}",),
            )
            for index, name in enumerate(tool_order, 1)
        ),
    )

    with pytest.raises(ValueError, match="without an admitted asset"):
        validate_plan(
            plan,
            allowed_tools=frozenset(tool_order),
            requires_multimodal=False,
        )
