"""HTTP schemas for claim-level provenance and report evidence timelines."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from disaster_monitor.application.evidence.inspection import EvidenceTimelineEventType
from disaster_monitor.domain.disaster import EvidenceDisposition, FactStatus
from disaster_monitor.presentation.http.event_schemas import SourceResponse


class EvidenceClaimVariantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    value: str
    status: FactStatus
    disposition: EvidenceDisposition
    source: SourceResponse
    observed_at: datetime | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    rule_id: str


class EvidenceClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_key: str
    label: str
    value: str | None
    status: FactStatus
    disposition: EvidenceDisposition | None
    why: str
    source: SourceResponse | None
    observed_at: datetime | None = None
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    alternatives: list[EvidenceClaimVariantResponse] = Field(default_factory=list)
    contradictions: list[EvidenceClaimVariantResponse] = Field(default_factory=list)
    gap: str | None = None


class EvidenceTimelineEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    event_type: EvidenceTimelineEventType
    occurred_at: datetime
    title: str
    detail: str
    source: SourceResponse | None
    status: str | None = None
    claim_key: str | None = None
    related_id: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
