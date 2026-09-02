"""Request-scoped decision tracing and pure trace validation/replay."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class TraceEventKind(StrEnum):
    TASK_VALIDATED = "task_validated"
    INITIAL_PLAN_VALIDATED = "initial_plan_validated"
    FOLLOWUP_PLAN_VALIDATED = "followup_plan_validated"
    MODEL_COMPLETED = "model_completed"
    MODEL_FAILED = "model_failed"
    TOOL_COMPLETED = "tool_completed"
    TOOL_SKIPPED = "tool_skipped"
    TOOL_FAILED = "tool_failed"
    BUDGET_VIOLATION = "budget_violation"
    SUFFICIENCY_ASSESSED = "sufficiency_assessed"
    REVIEW_DECISION = "review_decision"
    FOLLOWUP_SELECTED = "followup_selected"
    FOLLOWUP_REJECTED = "followup_rejected"
    FOLLOWUP_EXECUTED = "followup_executed"
    COMPOSITION = "composition"
    TERMINATION = "termination"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    """One stable event with no prompt, payload, or unrestricted provider text."""

    sequence: int
    kind: TraceEventKind
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("Trace sequences start at one.")
        if not isinstance(self.kind, TraceEventKind):
            object.__setattr__(self, "kind", TraceEventKind(self.kind))
        if tuple(sorted(self.attributes)) != self.attributes:
            raise ValueError("Trace attributes must be sorted deterministically.")

    @property
    def data(self) -> tuple[tuple[str, str], ...]:
        return self.attributes


@dataclass(slots=True)
class ExecutionTrace:
    """Mutable only while one request runs; callers observe immutable snapshots."""

    _events: list[TraceEvent] = field(default_factory=list, repr=False)

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        return tuple(self._events)

    def record(self, kind: TraceEventKind, **attributes: object) -> TraceEvent:
        event = TraceEvent(
            len(self._events) + 1,
            kind,
            tuple(
                sorted((key, _stable_value(value)) for key, value in attributes.items())
            ),
        )
        self._events.append(event)
        return event


class TraceValidationError(ValueError):
    """Raised when a captured decision trace cannot be a runtime execution."""


@dataclass(frozen=True, slots=True)
class TraceReplay:
    """Reconstructed counters and terminal state from a decision trace."""

    tool_call_count: int
    model_call_count: int
    replan_count: int
    composition_count: int
    terminated: bool
    final_event: TraceEventKind


def replay_trace(
    trace: ExecutionTrace | Iterable[TraceEvent],
) -> TraceReplay:
    """Validate/reconstruct decisions without invoking any external dependency."""
    events = trace.events if isinstance(trace, ExecutionTrace) else tuple(trace)
    if not events:
        raise TraceValidationError("A decision trace cannot be empty.")
    if tuple(event.sequence for event in events) != tuple(range(1, len(events) + 1)):
        raise TraceValidationError("Trace sequence numbers are not contiguous.")

    task_seen = False
    plan_seen = False
    evidence_assessments = 0
    review_seen = False
    review_decision: str | None = None
    review_selected: str | None = None
    available_options: set[str] = set()
    followup_pending = False
    followup_executed = False
    followup_plan_seen = False
    composition_count = 0
    terminated = False
    replans = 0
    tool_calls = 0
    model_calls = 0
    execution_failed = False

    for event in events:
        if terminated:
            raise TraceValidationError("Trace contains events after termination.")
        attributes = dict(event.attributes)
        kind = event.kind

        if kind is TraceEventKind.TASK_VALIDATED:
            if task_seen:
                raise TraceValidationError("Task validation occurred more than once.")
            if events[0] is not event:
                raise TraceValidationError("Task validation must be the first event.")
            task_seen = True
            continue

        if not task_seen:
            raise TraceValidationError("Trace event occurred before task validation.")

        if kind is TraceEventKind.INITIAL_PLAN_VALIDATED:
            if plan_seen or evidence_assessments:
                raise TraceValidationError("Initial plan validation is out of order.")
            plan_seen = True
        elif kind is TraceEventKind.FOLLOWUP_PLAN_VALIDATED:
            if not followup_pending or followup_executed or followup_plan_seen:
                raise TraceValidationError("Follow-up plan validation is out of order.")
            followup_plan_seen = True
        elif kind in {TraceEventKind.MODEL_COMPLETED, TraceEventKind.MODEL_FAILED}:
            if composition_count:
                raise TraceValidationError("Model activity occurred after composition.")
            counted = attributes.get("counted", "1")
            if counted not in {"0", "1", "false", "true"}:
                raise TraceValidationError("Model trace count is invalid.")
            if counted in {"1", "true"}:
                model_calls += 1
                if model_calls > 4:
                    raise TraceValidationError("Model-call budget was exceeded.")
        elif kind in {
            TraceEventKind.TOOL_COMPLETED,
            TraceEventKind.TOOL_SKIPPED,
            TraceEventKind.TOOL_FAILED,
        }:
            if composition_count:
                raise TraceValidationError("Tool activity occurred after composition.")
            if kind is TraceEventKind.TOOL_FAILED:
                execution_failed = True
            tool_calls += 1
            if tool_calls > 12:
                raise TraceValidationError("Tool-call budget was exceeded.")
            if not plan_seen:
                raise TraceValidationError("Tool execution occurred before planning.")
        elif kind is TraceEventKind.BUDGET_VIOLATION:
            if composition_count:
                raise TraceValidationError(
                    "Budget activity occurred after composition."
                )
            execution_failed = True
            if attributes.get("budget") not in {"tool_call", "model_call"}:
                raise TraceValidationError("Unknown trace budget.")
            if attributes["budget"] == "tool_call" and tool_calls < 12:
                raise TraceValidationError("Tool budget violation was premature.")
            if attributes["budget"] == "model_call" and model_calls < 4:
                raise TraceValidationError("Model budget violation was premature.")
        elif kind is TraceEventKind.SUFFICIENCY_ASSESSED:
            if not plan_seen or composition_count:
                raise TraceValidationError("Sufficiency assessment is out of order.")
            phase = attributes.get("phase")
            if phase not in {"initial", "followup"}:
                raise TraceValidationError("Sufficiency assessment phase is invalid.")
            if phase == "initial" and evidence_assessments:
                raise TraceValidationError("Initial sufficiency was assessed twice.")
            if phase == "followup" and not followup_executed:
                raise TraceValidationError("Follow-up sufficiency was assessed early.")
            if evidence_assessments >= 2:
                raise TraceValidationError("Sufficiency was assessed too many times.")
            evidence_assessments += 1
            if phase == "initial":
                available_options = {
                    option
                    for option in attributes.get("options", "").split(",")
                    if option
                }
        elif kind is TraceEventKind.REVIEW_DECISION:
            if evidence_assessments != 1 or review_seen:
                raise TraceValidationError("Review decision is out of order.")
            review_decision = attributes.get("decision")
            review_selected = attributes.get("selected", "") or ""
            if review_decision not in {"finish", "replan", "clarify"}:
                raise TraceValidationError("Review decision is invalid.")
            review_seen = True
        elif kind is TraceEventKind.FOLLOWUP_SELECTED:
            if (
                not review_seen
                or review_decision != "replan"
                or followup_pending
                or replans
            ):
                raise TraceValidationError("Follow-up selection is invalid.")
            option_id = attributes.get("option_id")
            if (
                not option_id
                or option_id not in available_options
                or review_selected != option_id
            ):
                raise TraceValidationError("Follow-up selection lacks an option ID.")
            followup_pending = True
            replans += 1
            if replans > 1:
                raise TraceValidationError("More than one replan is represented.")
        elif kind is TraceEventKind.FOLLOWUP_REJECTED:
            if (
                not review_seen
                or review_decision != "replan"
                or followup_pending
                or composition_count
            ):
                raise TraceValidationError("Follow-up rejection is invalid.")
        elif kind is TraceEventKind.FOLLOWUP_EXECUTED:
            if not followup_pending or followup_executed or not followup_plan_seen:
                raise TraceValidationError("Follow-up execution is invalid.")
            if attributes.get("result") not in {"completed", "failed"}:
                raise TraceValidationError("Follow-up result is invalid.")
            followup_executed = True
            followup_pending = False
        elif kind is TraceEventKind.COMPOSITION:
            if evidence_assessments < 1 or composition_count or not review_seen:
                raise TraceValidationError(
                    "Composition must follow review and evidence assessment and occur "
                    "once."
                )
            if followup_pending or evidence_assessments == 1 and replans:
                raise TraceValidationError("Composition occurred before follow-up.")
            composition_count += 1
        elif kind is TraceEventKind.TERMINATION:
            if attributes.get("reason") is None:
                raise TraceValidationError("Termination lacks a stable reason.")
            if followup_pending:
                raise TraceValidationError(
                    "Trace terminated during follow-up selection."
                )
            if plan_seen and not composition_count and not execution_failed:
                raise TraceValidationError(
                    "A validated plan terminated without composition."
                )
            terminated = True
        else:
            raise TraceValidationError(f"Unsupported trace event: {kind.value}.")

    if not terminated:
        raise TraceValidationError("Trace did not terminate.")
    if followup_pending:
        raise TraceValidationError("Trace ended with an unexecuted follow-up.")
    if replans and not followup_executed:
        raise TraceValidationError("A replan was selected but never executed.")
    return TraceReplay(
        tool_call_count=tool_calls,
        model_call_count=model_calls,
        replan_count=replans,
        composition_count=composition_count,
        terminated=True,
        final_event=TraceEventKind.TERMINATION,
    )


def validate_trace(trace: ExecutionTrace | Iterable[TraceEvent]) -> TraceReplay:
    """Explicit spelling for callers interested in validation rather than replay."""
    return replay_trace(trace)


def _stable_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (frozenset, set)):
        return ",".join(sorted(_stable_value(item) for item in value))
    if isinstance(value, (tuple, list)):
        return ",".join(_stable_value(item) for item in value)
    return str(value)


__all__ = [
    "ExecutionTrace",
    "TraceEvent",
    "TraceEventKind",
    "TraceReplay",
    "TraceValidationError",
    "replay_trace",
    "validate_trace",
]
