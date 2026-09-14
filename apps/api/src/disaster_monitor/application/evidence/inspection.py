"""Deterministic claim inspection and incident evidence timeline policy."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.domain.disaster import (
    ClaimEvidenceState,
    DisasterEvent,
    EvidenceDisposition,
    EvidenceObservationState,
    EvidenceWorldState,
    FactStatus,
    SituationReport,
    SourceReference,
)


class EvidenceTimelineEventType(StrEnum):
    """Typed entries retained in a report-scoped evidence timeline."""

    NORMALIZED_OBSERVATION = "normalized_observation"
    COVERAGE_STATUS = "coverage_status"
    WARNING_LIFECYCLE = "warning_lifecycle"
    SITUATION_REPORT = "situation_report"
    IMAGERY_ACQUISITION = "imagery_acquisition"
    IMAGERY_SELECTION = "imagery_selection"
    WATCH_CHANGE = "watch_change"
    CLAIM_RECONCILIATION = "claim_reconciliation"


@dataclass(frozen=True, slots=True)
class EvidenceClaimVariant:
    """One retained alternative observation for a material claim."""

    observation_id: str
    value: str
    status: FactStatus
    disposition: EvidenceDisposition
    source: SourceReference
    observed_at: datetime | None
    published_at: datetime | None
    retrieved_at: datetime
    rule_id: str


@dataclass(frozen=True, slots=True)
class EvidenceClaimInspection:
    """Operator-facing why/source/status details for one canonical claim."""

    claim_id: str
    claim_key: str
    label: str
    value: str | None
    status: FactStatus
    disposition: EvidenceDisposition | None
    why: str
    source: SourceReference | None
    observed_at: datetime | None
    published_at: datetime | None
    retrieved_at: datetime | None
    alternatives: tuple[EvidenceClaimVariant, ...] = ()
    contradictions: tuple[EvidenceClaimVariant, ...] = ()
    gap: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceTimelineEntry:
    """One immutable, time-ordered event in the incident evidence stream."""

    entry_id: str
    event_type: EvidenceTimelineEventType
    occurred_at: datetime
    title: str
    detail: str
    source: SourceReference | None = None
    status: str | None = None
    claim_key: str | None = None
    related_id: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.entry_id.strip() or not self.title.strip():
            raise ValueError("Timeline entries require stable identity and title.")
        for value in (self.occurred_at, self.published_at, self.retrieved_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("Timeline timestamps must be timezone-aware.")


def build_claim_inspections(
    world_state: EvidenceWorldState | None,
) -> tuple[EvidenceClaimInspection, ...]:
    """Expose every current claim, its retained alternatives, and explicit gaps."""
    if world_state is None:
        return ()
    return tuple(
        _claim_inspection(claim)
        for claim in sorted(world_state.claims, key=lambda item: item.claim_key)
    )


def build_evidence_timeline(
    event: DisasterEvent,
    reports: Iterable[SituationReport],
    world_state: EvidenceWorldState | None,
    *,
    warnings: Iterable[str] = (),
    retrieved_at: datetime | None = None,
    additional: Iterable[EvidenceTimelineEntry] = (),
) -> tuple[EvidenceTimelineEntry, ...]:
    """Merge event, claims, reports, warnings, and typed additions."""
    entries: list[EvidenceTimelineEntry] = [
        _entry(
            event_type=EvidenceTimelineEventType.NORMALIZED_OBSERVATION,
            occurred_at=event.event_time,
            title="Physical event observed",
            detail=f"{event.location}; source event {event.event_id}.",
            source=event.source,
            related_id=event.event_id,
        )
    ]
    if world_state is not None:
        for claim in world_state.claims:
            for state in claim.history:
                observation = state.observation
                fact = observation.fact
                entries.append(
                    _entry(
                        event_type=EvidenceTimelineEventType.NORMALIZED_OBSERVATION,
                        occurred_at=observation.chronology.effective_at,
                        title=f"Claim observed: {fact.label or claim.claim_key}",
                        detail=(
                            f"{fact.value} ({fact.status.value}); retained as "
                            f"{state.disposition.value}. Rule: {state.rule_id}."
                        ),
                        source=fact.source,
                        status=state.disposition.value,
                        claim_key=claim.claim_key,
                        related_id=observation.observation_id,
                        published_at=observation.chronology.published_at,
                        retrieved_at=observation.chronology.retrieved_at,
                    )
                )
                if state.disposition is EvidenceDisposition.CONFLICTING:
                    entries.append(
                        _entry(
                            event_type=EvidenceTimelineEventType.CLAIM_RECONCILIATION,
                            occurred_at=observation.chronology.effective_at,
                            title=(
                                f"Claim disagreement: {fact.label or claim.claim_key}"
                            ),
                            detail=(
                                "The observation remains visible as a conflicting "
                                "alternative; the current value was selected by the "
                                "canonical authority/time/status rule."
                            ),
                            source=fact.source,
                            status="conflicting",
                            claim_key=claim.claim_key,
                            related_id=observation.observation_id,
                        )
                    )
    for report in reports:
        entries.append(
            _entry(
                event_type=EvidenceTimelineEventType.SITUATION_REPORT,
                occurred_at=report.source.effective_at,
                title="Situation report updated",
                detail=report.narrative[:500] or "No narrative was supplied.",
                source=report.source,
                related_id=report.source.snapshot_id or report.source.source_id,
                published_at=report.source.published_at,
                retrieved_at=report.source.retrieved_at,
            )
        )
    if retrieved_at is not None:
        for warning in warnings:
            if warning.strip():
                entries.append(
                    _entry(
                        event_type=EvidenceTimelineEventType.COVERAGE_STATUS,
                        occurred_at=retrieved_at,
                        title="Coverage warning recorded",
                        detail=warning[:500],
                        status="degraded",
                        related_id="warning",
                        retrieved_at=retrieved_at,
                    )
                )
    entries.extend(additional)
    unique = {entry.entry_id: entry for entry in entries}
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.occurred_at, item.event_type.value, item.entry_id),
        )
    )


def _claim_inspection(claim: ClaimEvidenceState) -> EvidenceClaimInspection:
    current = claim.current
    variants = tuple(_variant(item) for item in claim.history)
    contradictions = tuple(
        item for item in variants if item.disposition is EvidenceDisposition.CONFLICTING
    )
    if current is None:
        return EvidenceClaimInspection(
            claim_id=_claim_id(claim.claim_key),
            claim_key=claim.claim_key,
            label=claim.claim_key.replace("_", " "),
            value=None,
            status=FactStatus.UNKNOWN,
            disposition=None,
            why="No usable observation was admitted for this claim.",
            source=None,
            observed_at=None,
            published_at=None,
            retrieved_at=None,
            alternatives=tuple(
                item
                for item in variants
                if item.disposition is not EvidenceDisposition.CURRENT
            ),
            contradictions=contradictions,
            gap="The configured sources did not provide a usable value.",
        )
    fact = current.fact
    gap = (
        "Conflicting source observations are retained below."
        if contradictions
        else None
    )
    selected_rule = next(
        item.rule_id for item in claim.history if item.observation is current
    )
    return EvidenceClaimInspection(
        claim_id=_claim_id(claim.claim_key),
        claim_key=claim.claim_key,
        label=fact.label or claim.claim_key,
        value=fact.value,
        status=fact.status,
        disposition=EvidenceDisposition.CURRENT,
        why=(
            f"Selected by {selected_rule} "
            f"from {fact.source.publisher}; source authority is "
            f"{fact.source.authority.value}."
        ),
        source=fact.source,
        observed_at=fact.observed_at,
        published_at=fact.source.published_at,
        retrieved_at=fact.source.retrieved_at,
        alternatives=tuple(
            item
            for item in variants
            if item.disposition is not EvidenceDisposition.CURRENT
        ),
        contradictions=contradictions,
        gap=gap,
    )


def _variant(state: EvidenceObservationState) -> EvidenceClaimVariant:
    observation = state.observation
    fact = observation.fact
    chronology = observation.chronology
    return EvidenceClaimVariant(
        observation_id=observation.observation_id,
        value=fact.value,
        status=fact.status,
        disposition=state.disposition,
        source=fact.source,
        observed_at=fact.observed_at,
        published_at=fact.source.published_at,
        retrieved_at=chronology.retrieved_at,
        rule_id=state.rule_id,
    )


def _claim_id(claim_key: str) -> str:
    return "claim:" + hashlib.sha256(claim_key.encode("utf-8")).hexdigest()[:24]


def _entry(
    *,
    event_type: EvidenceTimelineEventType,
    occurred_at: datetime,
    title: str,
    detail: str,
    source: SourceReference | None = None,
    status: str | None = None,
    claim_key: str | None = None,
    related_id: str | None = None,
    published_at: datetime | None = None,
    retrieved_at: datetime | None = None,
) -> EvidenceTimelineEntry:
    material = "|".join(
        (
            event_type.value,
            occurred_at.isoformat(),
            title,
            detail,
            source.source_id if source else "",
            related_id or "",
        )
    )
    entry_id = "timeline:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return EvidenceTimelineEntry(
        entry_id=entry_id,
        event_type=event_type,
        occurred_at=occurred_at,
        title=title,
        detail=detail,
        source=source,
        status=status,
        claim_key=claim_key,
        related_id=related_id,
        published_at=published_at,
        retrieved_at=retrieved_at,
    )


def evidence_timeline_entry(
    *,
    event_type: EvidenceTimelineEventType,
    occurred_at: datetime,
    title: str,
    detail: str,
    source: SourceReference | None = None,
    status: str | None = None,
    claim_key: str | None = None,
    related_id: str | None = None,
    published_at: datetime | None = None,
    retrieved_at: datetime | None = None,
) -> EvidenceTimelineEntry:
    """Create a stable typed addition for imagery, watch, or other evidence events."""
    return _entry(
        event_type=event_type,
        occurred_at=occurred_at,
        title=title,
        detail=detail,
        source=source,
        status=status,
        claim_key=claim_key,
        related_id=related_id,
        published_at=published_at,
        retrieved_at=retrieved_at,
    )
