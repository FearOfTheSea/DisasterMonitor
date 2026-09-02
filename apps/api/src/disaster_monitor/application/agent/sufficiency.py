"""Deterministic evidence-sufficiency policy for the bounded agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from disaster_monitor.application.agent.models import AgentExecutionState


class EvidenceSufficiencyState(StrEnum):
    """Stable outcomes of the application evidence gate."""

    SUFFICIENT = "sufficient"
    FOLLOWUP_AVAILABLE = "followup_available"
    TERMINAL_GAP = "terminal_gap"


class EvidenceGapCode(StrEnum):
    """Bounded, provider-neutral explanations for an evidence gap."""

    EVENT_NOT_ESTABLISHED = "event_not_established"
    RETRYABLE_EVENT_DISCOVERY = "retryable_event_discovery"
    SITUATION_EVIDENCE_MISSING = "situation_evidence_missing"
    RETRYABLE_SITUATION_EVIDENCE = "retryable_situation_evidence"
    NON_RETRYABLE_PROVIDER_ISSUE = "non_retryable_provider_issue"
    UNSUPPORTED_INFORMATION_ROLE = "unsupported_information_role"
    MISSING_PROVIDER_CONFIGURATION = "missing_provider_configuration"
    ORDINARY_CAPABILITY_GAP = "ordinary_capability_gap"
    PARTIAL_EVIDENCE = "partial_evidence"


class FollowUpOptionId(StrEnum):
    """The only follow-up actions production policy can authorize."""

    RETRY_EVENT_DISCOVERY = "retry_event_discovery"
    RETRY_SITUATION_EVIDENCE = "retry_situation_evidence"


@dataclass(frozen=True, slots=True)
class FollowUpOption:
    """A bounded option exposed to the review model."""

    option_id: str
    description: str


@dataclass(frozen=True, slots=True)
class EvidenceSufficiencyAssessment:
    """A model-independent assessment of the currently admitted workspace."""

    state: EvidenceSufficiencyState
    gap_codes: tuple[EvidenceGapCode, ...] = ()
    follow_up_options: tuple[FollowUpOption, ...] = ()

    @property
    def status(self) -> EvidenceSufficiencyState:
        """Compatibility spelling for callers that call the state a status."""
        return self.state

    @property
    def gaps(self) -> tuple[EvidenceGapCode, ...]:
        return self.gap_codes

    @property
    def option_ids(self) -> tuple[str, ...]:
        return tuple(option.option_id for option in self.follow_up_options)


_FOLLOW_UP_DESCRIPTIONS = {
    FollowUpOptionId.RETRY_EVENT_DISCOVERY: (
        "Retry event discovery once, then rerun dependent situation retrieval and "
        "evidence reconciliation."
    ),
    FollowUpOptionId.RETRY_SITUATION_EVIDENCE: (
        "Retry situation evidence retrieval once, then rerun evidence reconciliation."
    ),
}


def assess_evidence_sufficiency(
    state: AgentExecutionState,
) -> EvidenceSufficiencyAssessment:
    """Assess only typed, already-admitted state; never consult model output."""
    workspace = state.workspace
    gaps: list[EvidenceGapCode] = []

    if (
        workspace.source_selection is not None
        and workspace.source_selection.unsupported_roles
    ):
        gaps.append(EvidenceGapCode.UNSUPPORTED_INFORMATION_ROLE)
    if (
        workspace.source_selection is not None
        and workspace.source_selection.unconfigured_source_ids
        and not workspace.source_selection.configured_source_ids
    ):
        gaps.append(EvidenceGapCode.MISSING_PROVIDER_CONFIGURATION)

    if workspace.event_batch is None or workspace.selected_event is None:
        gaps.append(EvidenceGapCode.EVENT_NOT_ESTABLISHED)
        event_issues = (
            workspace.event_batch.issues if workspace.event_batch is not None else ()
        )
        if any(issue.retryable for issue in event_issues):
            gaps.append(EvidenceGapCode.RETRYABLE_EVENT_DISCOVERY)
            if state.replan_count == 0:
                return _assessment(
                    EvidenceSufficiencyState.FOLLOWUP_AVAILABLE,
                    gaps,
                    (FollowUpOptionId.RETRY_EVENT_DISCOVERY,),
                )
        elif event_issues:
            gaps.append(EvidenceGapCode.NON_RETRYABLE_PROVIDER_ISSUE)
        return _assessment(EvidenceSufficiencyState.TERMINAL_GAP, gaps)

    situation_batch = workspace.situation_batch
    situation_issues = situation_batch.issues if situation_batch is not None else ()
    if any(issue.retryable for issue in situation_issues):
        gaps.append(EvidenceGapCode.RETRYABLE_SITUATION_EVIDENCE)
        if state.replan_count == 0:
            return _assessment(
                EvidenceSufficiencyState.FOLLOWUP_AVAILABLE,
                gaps,
                (FollowUpOptionId.RETRY_SITUATION_EVIDENCE,),
            )
    elif situation_issues:
        gaps.append(EvidenceGapCode.NON_RETRYABLE_PROVIDER_ISSUE)

    packet = workspace.evidence_packet
    if packet is None:
        gaps.append(EvidenceGapCode.SITUATION_EVIDENCE_MISSING)
        return _assessment(EvidenceSufficiencyState.TERMINAL_GAP, gaps)

    if packet.completeness == "event_verified_no_situation_evidence":
        gaps.append(EvidenceGapCode.SITUATION_EVIDENCE_MISSING)
    elif packet.completeness != "event_verified_with_event_specific_evidence":
        gaps.append(EvidenceGapCode.PARTIAL_EVIDENCE)

    if state.plan.capability_gaps:
        gaps.append(EvidenceGapCode.ORDINARY_CAPABILITY_GAP)

    if gaps:
        return _assessment(EvidenceSufficiencyState.TERMINAL_GAP, gaps)
    return _assessment(EvidenceSufficiencyState.SUFFICIENT, gaps)


def follow_up_option(option_id: str) -> FollowUpOption | None:
    """Return one application-owned option, never a model-created option."""
    try:
        typed_id = FollowUpOptionId(option_id)
    except ValueError:
        return None
    return FollowUpOption(typed_id.value, _FOLLOW_UP_DESCRIPTIONS[typed_id])


def _assessment(
    status: EvidenceSufficiencyState,
    gaps: list[EvidenceGapCode],
    option_ids: tuple[FollowUpOptionId, ...] = (),
) -> EvidenceSufficiencyAssessment:
    ordered_gaps = tuple(dict.fromkeys(gaps))
    options = tuple(
        FollowUpOption(option_id.value, _FOLLOW_UP_DESCRIPTIONS[option_id])
        for option_id in option_ids
    )
    return EvidenceSufficiencyAssessment(status, ordered_gaps, options)


# Short aliases make the policy easy to discover without multiplying concepts.
SufficiencyState = EvidenceSufficiencyState
GapCode = EvidenceGapCode


__all__ = [
    "EvidenceGapCode",
    "EvidenceSufficiencyAssessment",
    "EvidenceSufficiencyState",
    "FollowUpOption",
    "FollowUpOptionId",
    "GapCode",
    "SufficiencyState",
    "assess_evidence_sufficiency",
    "follow_up_option",
]
