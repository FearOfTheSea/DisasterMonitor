"""Serialize claim and timeline application records for the HTTP boundary."""

from disaster_monitor.application.evidence.inspection import (
    EvidenceClaimInspection,
    EvidenceClaimVariant,
    EvidenceTimelineEntry,
)
from disaster_monitor.presentation.http.common_response_serialization import (
    _source_response,
)
from disaster_monitor.presentation.http.evidence_schemas import (
    EvidenceClaimResponse,
    EvidenceClaimVariantResponse,
    EvidenceTimelineEntryResponse,
)


def evidence_claim_response(value: EvidenceClaimInspection) -> EvidenceClaimResponse:
    return EvidenceClaimResponse(
        claim_id=value.claim_id,
        claim_key=value.claim_key,
        label=value.label,
        value=value.value,
        status=value.status,
        disposition=value.disposition,
        why=value.why,
        source=(_source_response(value.source) if value.source is not None else None),
        observed_at=value.observed_at,
        published_at=value.published_at,
        retrieved_at=value.retrieved_at,
        alternatives=[_claim_variant_response(item) for item in value.alternatives],
        contradictions=[_claim_variant_response(item) for item in value.contradictions],
        gap=value.gap,
    )


def evidence_timeline_response(
    value: EvidenceTimelineEntry,
) -> EvidenceTimelineEntryResponse:
    return EvidenceTimelineEntryResponse(
        entry_id=value.entry_id,
        event_type=value.event_type,
        occurred_at=value.occurred_at,
        title=value.title,
        detail=value.detail,
        source=(_source_response(value.source) if value.source is not None else None),
        status=value.status,
        claim_key=value.claim_key,
        related_id=value.related_id,
        published_at=value.published_at,
        retrieved_at=value.retrieved_at,
    )


def _claim_variant_response(
    value: EvidenceClaimVariant,
) -> EvidenceClaimVariantResponse:
    return EvidenceClaimVariantResponse(
        observation_id=value.observation_id,
        value=value.value,
        status=value.status,
        disposition=value.disposition,
        source=_source_response(value.source),
        observed_at=value.observed_at,
        published_at=value.published_at,
        retrieved_at=value.retrieved_at,
        rule_id=value.rule_id,
    )
