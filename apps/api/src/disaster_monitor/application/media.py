"""Disaster-neutral application contracts for event-associated source media."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from disaster_monitor.domain.disaster import Disaster


class MediaAssociationStatus(StrEnum):
    """Strength of the deterministic relationship to the selected event."""

    EXACT_EVENT_LINK = "exact_event_link"
    CORROBORATED = "corroborated"
    REJECTED = "rejected"


class MediaRightsStatus(StrEnum):
    """What Disaster Monitor may claim about presentation rights."""

    LICENSED_REUSE = "licensed_reuse"
    SOURCE_PREVIEW = "source_preview"


class MediaCreditKind(StrEnum):
    PHOTOGRAPHER = "photographer"
    AGENCY = "agency"
    PUBLISHER = "publisher"


class MediaContentRole(StrEnum):
    """Generic disaster-media roles; these are not disaster classifications."""

    AFTERMATH = "aftermath"
    RESCUE_EFFORT = "rescue_effort"
    RELIEF_OPERATION = "relief_operation"
    SCIENTIFIC_OVERVIEW = "scientific_overview"
    RELEVANT_SCENE = "relevant_scene"


@dataclass(frozen=True, slots=True)
class MediaEventContext:
    """Application-owned search context derived from a selected event."""

    event_id: str
    physical_event_id: str
    disaster: Disaster
    location: str
    event_time: datetime
    provider_ids: tuple[str, ...]
    country_code: str | None
    country_terms: tuple[str, ...]
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True, slots=True)
class DisasterMediaCandidate:
    """Source-page metadata discovered by one bounded provider."""

    candidate_id: str
    provider_id: str
    source_id: str
    publisher: str
    source_page_url: str
    image_url: str
    article_title: str
    context_text: str
    caption: str
    credit: str
    credit_kind: MediaCreditKind
    published_at: datetime
    captured_at: datetime | None
    license_name: str | None
    license_url: str | None
    rights_status: MediaRightsStatus
    source_priority: int


@dataclass(frozen=True, slots=True)
class MediaCandidateAssessment:
    candidate: DisasterMediaCandidate
    status: MediaAssociationStatus
    rule_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class RetrievedMedia:
    candidate: DisasterMediaCandidate
    content: bytes
    media_type: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class StoredMediaAsset:
    media_id: str
    content: bytes
    media_type: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class DisasterMediaItem:
    """One presentation-safe item that remains separate from reported facts."""

    media_id: str
    event_id: str
    physical_event_id: str
    source_id: str
    publisher: str
    source_page_url: str
    caption: str
    credit: str
    credit_kind: MediaCreditKind
    published_at: datetime
    captured_at: datetime | None
    license_name: str | None
    license_url: str | None
    rights_status: MediaRightsStatus
    role: MediaContentRole
    association_status: MediaAssociationStatus
    association_rule_ids: tuple[str, ...]
    association_detail: str
    uncertainty: str
    content_sha256: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class DisasterMediaGallery:
    event_id: str
    physical_event_id: str
    generated_at: datetime
    items: tuple[DisasterMediaItem, ...]
    rejected_count: int
    provider_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()
