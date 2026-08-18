"""Normalize provider records into a bounded, source-attributed evidence packet."""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from html import unescape
from typing import Protocol

from disaster_monitor.application.disaster import DisasterQuery, EvidencePacket
from disaster_monitor.application.services.evidence_correlation import (
    correlate_situation_report,
    default_evidence_correlation_policies,
)
from disaster_monitor.application.services.evidence_state import (
    build_evidence_world_state,
    source_is_stale,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    DisasterEvent,
    EvidenceDisposition,
    EvidenceFreshness,
    FactStatus,
    Hazard,
    PhysicalEventIdentity,
    ReportedFact,
    SituationReport,
    SourceReference,
)

MAX_NARRATIVE_LENGTH = 1_200
_TAG = re.compile(r"<[^>]+>")
_INSTRUCTION_FRAGMENT = re.compile(
    r"\b(?:ignore|disregard|override|system message|developer message|"
    r"tool call|prompt injection)(?:\s+\w+){0,4}[.!?:;]?",
    re.IGNORECASE,
)


class _CorrelationPolicy(Protocol):
    def correlate(
        self, report: SituationReport, event: DisasterEvent
    ) -> CorrelationStatus: ...


class _CorrelationPolicies(Protocol):
    def for_hazard(self, hazard: Hazard) -> _CorrelationPolicy: ...


def sanitize_provider_text(text: str, *, limit: int = MAX_NARRATIVE_LENGTH) -> str:
    """Remove markup, control characters, and instruction-like provider text."""
    cleaned = _TAG.sub(" ", unescape(text))
    lines = []
    for line in cleaned.splitlines():
        safe_line = _INSTRUCTION_FRAGMENT.sub(" ", line)
        safe_line = re.sub(r"\s+", " ", safe_line).strip()
        if safe_line:
            lines.append(safe_line)
    cleaned = re.sub(r"\s+", " ", " ".join(lines)).strip()
    return cleaned[:limit]


def normalize_timestamp(value: object) -> datetime | None:
    """Normalize provider-neutral datetime and Unix timestamp values."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 100_000_000_000:
            number /= 1_000
        return datetime.fromtimestamp(number, tz=UTC)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _has_correlation_metadata(report: SituationReport) -> bool:
    return bool(
        report.event_id
        or report.provider_event_ids
        or report.reported_event_time
        or report.locations
        or report.countries
        or report.country_codes
        or report.hazard is not None
        or report.measurements
    )


def _source_key(source: SourceReference) -> str:
    return source.canonical_url.rstrip("/").lower()


def _deduplicate_reports(
    reports: tuple[SituationReport, ...],
) -> tuple[SituationReport, ...]:
    unique: dict[str, SituationReport] = {}
    ordered = sorted(
        reports,
        key=lambda report: (
            report.source.effective_at,
            report.source.source_id,
            report.source.canonical_url,
        ),
    )
    for report in ordered:
        narrative_key = re.sub(r"\W+", " ", report.narrative.lower()).strip()[:240]
        key = narrative_key if len(narrative_key) >= 40 else _source_key(report.source)
        current = unique.get(key)
        if current is None or (
            report.source.effective_at,
            report.source.source_id,
            report.source.canonical_url,
        ) > (
            current.source.effective_at,
            current.source.source_id,
            current.source.canonical_url,
        ):
            unique[key] = report
    return tuple(
        sorted(
            unique.values(),
            key=lambda report: (
                report.source.effective_at,
                report.source.source_id,
                report.source.canonical_url,
            ),
        )
    )


def build_evidence_packet(
    query: DisasterQuery,
    event: DisasterEvent,
    reports: tuple[SituationReport, ...],
    *,
    warnings: tuple[str, ...],
    retrieved_at: datetime,
    physical_event: PhysicalEventIdentity | None = None,
    correlation: Callable[
        [SituationReport, DisasterEvent], CorrelationStatus
    ] = correlate_situation_report,
) -> EvidencePacket:
    """Reconcile duplicate, newer, missing, and conflicting provider facts."""
    correlated_reports: list[SituationReport] = []
    correlation_warning_counts: dict[tuple[CorrelationStatus, str], int] = {}
    for report in reports:
        hard_scope_mismatch = (
            report.hazard is not None
            and report.hazard != query.hazard
            or bool(report.country_codes)
            and query.country.alpha3_code
            not in {code.upper() for code in report.country_codes}
        )
        status = (
            CorrelationStatus.UNMATCHED
            if hard_scope_mismatch
            else correlation(report, event)
        )
        if report.correlation is not None or _has_correlation_metadata(report):
            if status == CorrelationStatus.MATCHED:
                correlated_reports.append(report)
            else:
                key = (status, report.source.publisher)
                correlation_warning_counts[key] = (
                    correlation_warning_counts.get(key, 0) + 1
                )
        else:
            correlated_reports.append(report)
    correlation_warnings: list[str] = []
    for (status, publisher), count in correlation_warning_counts.items():
        article = "report" if count == 1 else "reports"
        quantity = "A" if count == 1 else str(count)
        if status == CorrelationStatus.POSSIBLE:
            correlation_warnings.append(
                f"{quantity} {publisher} {article} may describe a different "
                f"{query.hazard.value} event in {query.country.canonical_name} "
                "and was excluded from event facts."
            )
        else:
            correlation_warnings.append(
                f"{quantity} {publisher} {article} did not match the selected "
                f"{query.hazard.value} event in {query.country.canonical_name} "
                "and was excluded."
            )
    normalized_reports: list[SituationReport] = []
    for report in correlated_reports:
        normalized_facts: list[ReportedFact] = []
        for fact in report.facts:
            safe_value = sanitize_provider_text(fact.value, limit=240)
            if not safe_value and fact.status != FactStatus.UNKNOWN:
                continue
            if fact.event_id and not event.has_provider_id(fact.event_id):
                continue
            normalized_facts.append(
                ReportedFact(
                    category=fact.category,
                    label=sanitize_provider_text(fact.label, limit=120),
                    value=safe_value,
                    status=fact.status,
                    source=fact.source,
                    event_id=fact.event_id or report.event_id or event.event_id,
                    observed_at=fact.observed_at,
                    claim_id=fact.claim_id,
                )
            )
        normalized_reports.append(
            replace(
                report,
                narrative=sanitize_provider_text(report.narrative),
                facts=tuple(normalized_facts),
            )
        )
    reports = tuple(normalized_reports)
    world_state = build_evidence_world_state(
        event,
        reports,
        evaluated_at=retrieved_at,
        physical_event=physical_event,
    )
    selected = [
        claim.current.fact for claim in world_state.claims if claim.current is not None
    ]
    conflicts: list[str] = []
    for claim in world_state.claims:
        conflicting = tuple(
            item
            for item in claim.history
            if item.disposition == EvidenceDisposition.CONFLICTING
        )
        if claim.current is not None and conflicting:
            observations = (claim.current, *(item.observation for item in conflicting))
            summary = "; ".join(
                f"{item.fact.source.publisher}: {item.fact.value}"
                for item in observations[:4]
            )
            conflicts.append(
                f"{claim.current.fact.label or claim.claim_key}: {summary}."
            )

    projection_reports = _deduplicate_reports(reports)

    sources: list[SourceReference] = [event.source]
    for report in projection_reports:
        if _source_key(report.source) not in {_source_key(item) for item in sources}:
            sources.append(report.source)
    event_source_key = _source_key(event.source)
    stale = any(
        _source_key(report.source) != event_source_key
        and source_is_stale(report.source.effective_at, retrieved_at)
        for report in projection_reports
    ) or any(
        item.freshness == EvidenceFreshness.STALE
        for claim in world_state.claims
        for item in claim.history
    )
    stale_warning = (
        ("Some source updates are stale (more than 24 hours old).",) if stale else ()
    )
    narratives = tuple(
        f"{narrative} Source: {report.source.publisher} — {report.source.title} "
        f"({report.source.canonical_url})"
        for report in projection_reports
        if (narrative := report.narrative)
    )
    impact_categories = {
        "fatalities",
        "injuries",
        "missing",
        "rescued",
        "rescue_operations",
        "evacuations",
        "shelters",
        "buildings",
        "buildings_destroyed",
        "buildings_damaged",
        "fires",
        "landslides",
        "roads",
        "rail",
        "airports",
        "ports",
        "utilities",
        "infrastructure",
        "communications",
        "critical_facilities",
        "damage_status",
        "tsunami",
        "response",
        "government_response",
        "emergency_response",
    }
    has_impact_facts = any(fact.category in impact_categories for fact in selected)
    has_impact_narrative = any(
        re.search(
            r"\b(?:damage|damaged|destroyed|closed|blocked|outage|shelter|rescue|"
            r"evacu|injur|killed|fatalit|inspection|closure|disrupt)",
            report.narrative,
            re.IGNORECASE,
        )
        for report in projection_reports
    )
    non_stale_warnings = tuple(
        warning
        for warning in (*warnings, *correlation_warnings)
        if "stale" not in warning.lower()
    )
    if not reports:
        completeness = "event_verified_no_situation_evidence"
        completeness_warning = (
            "No reliable event-specific damage or situation information was found; "
            "this does not mean that no damage occurred."
        )
    elif not has_impact_facts and not has_impact_narrative:
        completeness = "event_verified_no_relevant_impact_evidence"
        completeness_warning = (
            "Situation reports were retrieved, but no reliable event-specific damage "
            "or impact evidence was found; this does not mean that no damage occurred."
        )
    elif non_stale_warnings:
        completeness = "event_verified_partial_provider_success"
        completeness_warning = (
            "Some configured situation sources did not provide usable data."
        )
    else:
        completeness = "event_verified_with_event_specific_evidence"
        completeness_warning = None
    packet_warnings = list(dict.fromkeys((*warnings, *correlation_warnings)))
    if completeness_warning:
        packet_warnings.append(completeness_warning)
    partial = completeness != "event_verified_with_event_specific_evidence"
    return EvidencePacket(
        query=query,
        event=event,
        facts=tuple(sorted(selected, key=lambda fact: (fact.category, fact.label))),
        narratives=narratives[:6],
        sources=tuple(sources[:10]),
        conflicts=tuple(conflicts[:8]),
        warnings=tuple(dict.fromkeys((*packet_warnings, *stale_warning))),
        retrieved_at=retrieved_at,
        stale=stale,
        completeness=completeness,
        partial=partial,
        world_state=world_state,
    )


class EvidenceReconciler:
    """Injectable application service for deterministic evidence reconciliation."""

    def __init__(
        self, correlation_policies: _CorrelationPolicies | None = None
    ) -> None:
        self._correlation_policies = correlation_policies

    def build(
        self,
        query: DisasterQuery,
        event: DisasterEvent,
        reports: tuple[SituationReport, ...],
        *,
        warnings: tuple[str, ...],
        retrieved_at: datetime,
        physical_event: PhysicalEventIdentity | None = None,
    ) -> EvidencePacket:
        policies: _CorrelationPolicies
        if self._correlation_policies is None:
            policies = default_evidence_correlation_policies()
        else:
            policies = self._correlation_policies
        return build_evidence_packet(
            query,
            event,
            reports,
            warnings=warnings,
            retrieved_at=retrieved_at,
            physical_event=physical_event,
            correlation=policies.for_hazard(query.hazard).correlate,
        )
