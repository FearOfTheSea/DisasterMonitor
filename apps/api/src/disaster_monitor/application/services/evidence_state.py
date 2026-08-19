"""Canonical temporal evidence-state construction and chronology policy."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.domain.disaster import (
    ClaimEvidenceState,
    DisasterEvent,
    EvidenceAvailability,
    EvidenceChronology,
    EvidenceDisposition,
    EvidenceFreshness,
    EvidenceObservation,
    EvidenceObservationState,
    EvidenceWorldState,
    FactStatus,
    PhysicalEventIdentity,
    ReportedFact,
    SituationReport,
    SourceAuthority,
)

STALE_AFTER = timedelta(hours=24)
_MISSING_VALUES = frozenset(
    {"", "unknown", "not available", "not reported", "n/a", "na", "missing"}
)


def effective_chronology(fact: ReportedFact) -> EvidenceChronology:
    """Apply the one chronology precedence used by reconciliation and evaluation.

    A publisher correction time is strongest, then publication time, then the
    observation time stated for the fact, and finally retrieval time.
    """
    source = fact.source
    effective_at = (
        source.updated_at
        or source.published_at
        or fact.observed_at
        or source.retrieved_at
    )
    return EvidenceChronology(
        observed_at=fact.observed_at,
        published_at=source.published_at,
        updated_at=source.updated_at,
        retrieved_at=source.retrieved_at,
        effective_at=_aware(effective_at),
    )


def claim_key(fact: ReportedFact) -> str:
    return fact.claim_id or fact.category


def source_authority_priority(authority: SourceAuthority) -> int:
    return {
        SourceAuthority.NATIONAL_AUTHORITY: 4,
        SourceAuthority.SCIENTIFIC_AUTHORITY: 3,
        SourceAuthority.HUMANITARIAN_AGGREGATOR: 2,
        SourceAuthority.SECONDARY: 1,
    }[authority]


def fact_status_priority(status: FactStatus) -> int:
    return {
        FactStatus.CONFIRMED: 5,
        FactStatus.PRELIMINARY: 4,
        FactStatus.ESTIMATED: 3,
        FactStatus.DISPUTED: 2,
        FactStatus.UNKNOWN: 1,
    }[status]


def is_usable_fact(fact: ReportedFact) -> bool:
    return (
        fact.status != FactStatus.UNKNOWN
        and fact.value.strip().casefold() not in _MISSING_VALUES
    )


def _observation_id(fact: ReportedFact, report: SituationReport) -> str:
    chronology = effective_chronology(fact)
    chronology_material = (
        chronology.observed_at.isoformat() if chronology.observed_at else "",
        chronology.published_at.isoformat() if chronology.published_at else "",
        chronology.updated_at.isoformat() if chronology.updated_at else "",
        chronology.retrieved_at.isoformat(),
    )
    material = "|".join(
        (
            fact.source.source_id.casefold(),
            fact.source.canonical_url.casefold(),
            claim_key(fact).casefold(),
            fact.category.casefold(),
            fact.label.casefold(),
            fact.value.strip().casefold(),
            fact.status.value,
            *(item for item in chronology_material),
            fact.event_id or "",
            report.source.canonical_url.casefold(),
        )
    )
    return f"evidence:{sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _selection_key(
    observation: EvidenceObservation,
) -> tuple[int, datetime, int, str, str, str]:
    fact = observation.fact
    return (
        source_authority_priority(fact.source.authority),
        observation.chronology.effective_at,
        fact_status_priority(fact.status),
        fact.source.source_id,
        fact.source.canonical_url,
        observation.observation_id,
    )


def _history_key(state: EvidenceObservationState) -> tuple[datetime, str]:
    return (
        state.observation.chronology.effective_at,
        state.observation.observation_id,
    )


def _freshness(
    observation: EvidenceObservation, evaluated_at: datetime
) -> EvidenceFreshness:
    return (
        EvidenceFreshness.STALE
        if _aware(evaluated_at) - observation.chronology.effective_at > STALE_AFTER
        else EvidenceFreshness.FRESH
    )


def source_is_stale(source_time: datetime, evaluated_at: datetime) -> bool:
    """Apply the canonical 24-hour freshness boundary to a source time."""
    return _aware(evaluated_at) - _aware(source_time) > STALE_AFTER


def _classify_claim(
    key: str,
    observations: tuple[EvidenceObservation, ...],
    reports: tuple[SituationReport, ...],
    evaluated_at: datetime,
) -> ClaimEvidenceState:
    usable = tuple(item for item in observations if is_usable_fact(item.fact))
    selected = max(usable, key=_selection_key) if usable else None
    states: list[EvidenceObservationState] = []
    for observation in observations:
        if not is_usable_fact(observation.fact):
            disposition = EvidenceDisposition.UNUSABLE
            rule_id = "ew.missing.explicit_unknown"
        elif observation == selected:
            disposition = EvidenceDisposition.CURRENT
            rule_id = "ew.selection.authority_time_status"
        elif selected is not None and (
            observation.fact.source.source_id == selected.fact.source.source_id
        ):
            disposition = EvidenceDisposition.SUPERSEDED
            rule_id = "ew.revision.same_source"
        elif selected is not None and (
            observation.fact.value.strip().casefold()
            == selected.fact.value.strip().casefold()
        ):
            disposition = EvidenceDisposition.DUPLICATE
            rule_id = "ew.duplicate.same_claim_value"
        else:
            disposition = EvidenceDisposition.CONFLICTING
            rule_id = "ew.conflict.material_disagreement"
        states.append(
            EvidenceObservationState(
                observation=observation,
                disposition=disposition,
                freshness=_freshness(observation, evaluated_at),
                rule_id=rule_id,
            )
        )
    latest_by_source: dict[str, datetime] = {}
    for observation in observations:
        source_id = observation.fact.source.source_id
        latest_by_source[source_id] = max(
            latest_by_source.get(source_id, observation.chronology.effective_at),
            observation.chronology.effective_at,
        )
    omission_reports = tuple(
        report.source
        for report in reports
        if report.source.source_id in latest_by_source
        and report.source.effective_at > latest_by_source[report.source.source_id]
        and key not in {claim_key(fact) for fact in report.facts}
    )
    return ClaimEvidenceState(
        claim_key=key,
        availability=(
            EvidenceAvailability.PRESENT
            if selected is not None
            else EvidenceAvailability.ABSENT
        ),
        current=selected,
        history=tuple(sorted(states, key=_history_key, reverse=True)),
        omission_reports=tuple(
            sorted(
                omission_reports,
                key=lambda source: (
                    source.effective_at,
                    source.source_id,
                    source.canonical_url,
                ),
            )
        ),
    )


def build_evidence_world_state(
    event: DisasterEvent,
    reports: tuple[SituationReport, ...],
    *,
    evaluated_at: datetime,
    physical_event: PhysicalEventIdentity | None = None,
) -> EvidenceWorldState:
    """Build order-independent current claim state without deleting history."""
    if physical_event is None:
        identity = (
            default_event_policy_registry()
            .for_disaster(event.disaster)
            .identify((event,))
        )
        physical_event = identity.physical_events[0]

    observations_by_claim: dict[str, list[EvidenceObservation]] = defaultdict(list)
    unique_observations: set[str] = set()
    ordered_reports = tuple(
        sorted(
            reports,
            key=lambda report: (
                report.source.effective_at,
                report.source.source_id,
                report.source.canonical_url,
                report.narrative,
            ),
        )
    )
    for report in ordered_reports:
        for fact in report.facts:
            observation_id = _observation_id(fact, report)
            if observation_id in unique_observations:
                continue
            unique_observations.add(observation_id)
            key = claim_key(fact)
            observations_by_claim[key].append(
                EvidenceObservation(
                    observation_id=observation_id,
                    claim_key=key,
                    fact=fact,
                    report=report,
                    chronology=effective_chronology(fact),
                )
            )
    claims = tuple(
        _classify_claim(
            key,
            tuple(observations_by_claim[key]),
            ordered_reports,
            evaluated_at,
        )
        for key in sorted(observations_by_claim)
    )
    version_material = "|".join(
        (
            physical_event.physical_event_id,
            _aware(evaluated_at).isoformat(),
            *(
                f"report:{report.source.source_id}:{report.source.canonical_url}:"
                f"{report.source.effective_at.isoformat()}:{report.narrative}"
                for report in ordered_reports
            ),
            *(
                f"{claim.claim_key}:{state.observation.observation_id}:"
                f"{state.disposition.value}:{state.freshness.value}"
                for claim in claims
                for state in claim.history
            ),
            *(
                f"{claim.claim_key}:omission:{source.source_id}:"
                f"{source.canonical_url}:{source.effective_at.isoformat()}"
                for claim in claims
                for source in claim.omission_reports
            ),
        )
    )
    state_version = (
        f"world-state:{sha256(version_material.encode('utf-8')).hexdigest()[:24]}"
    )
    return EvidenceWorldState(
        state_version=state_version,
        physical_event=physical_event,
        claims=claims,
        reports=ordered_reports,
        evaluated_at=_aware(evaluated_at),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
