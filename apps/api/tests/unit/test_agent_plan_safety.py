import pytest

from disaster_monitor.application.agent.models import InvestigationPlan, PlanStep
from disaster_monitor.application.agent.planning import (
    DEFAULT_TOOL_ORDER,
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
