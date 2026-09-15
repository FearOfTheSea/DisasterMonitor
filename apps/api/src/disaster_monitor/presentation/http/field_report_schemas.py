"""Transport schemas for field reports and humanitarian context."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from disaster_monitor.domain.field_reports import (
    FieldReportReviewDecision,
    LocationPrecision,
)


class FieldAttachmentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    media_type: Literal["image/jpeg", "image/png"]
    content_base64: str = Field(min_length=1, max_length=12_000_000)


class FieldGeometryRequest(BaseModel):
    type: Literal["Point", "Polygon"]
    coordinates: list[object]


class FieldReportCreateRequest(BaseModel):
    report_type: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=10_000)
    captured_at: datetime
    source_created_at: datetime
    submitter_channel: str = Field(min_length=1, max_length=100)
    geometry: FieldGeometryRequest
    location_precision: LocationPrecision
    location_uncertainty_m: float | None = Field(default=None, gt=0, le=100_000)
    attachments: list[FieldAttachmentRequest] = Field(
        default_factory=list, max_length=4
    )


class FieldReportReviewRequest(BaseModel):
    decision: FieldReportReviewDecision
    reviewer_id: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2_000)
    event_id: str | None = Field(default=None, min_length=1, max_length=500)
    authority_policy_id: str | None = Field(default=None, min_length=1, max_length=200)


class ExternalFieldMappingRequest(BaseModel):
    external_id: str
    report_type: str
    text: str
    captured_at: str
    source_created_at: str
    latitude: str
    longitude: str
    external_verification: str | None = None


class FieldReportImportRequest(BaseModel):
    source_system: Literal["kobotoolbox", "odk", "ushahidi"]
    format: Literal["csv", "geojson", "ushahidi"]
    content: str | dict[str, object]
    reviewed_by: str = Field(min_length=1, max_length=200)
    mapping: ExternalFieldMappingRequest | None = None
    media_packages: list["ImportedFieldMediaRequest"] = Field(
        default_factory=list, max_length=4_000
    )


class ImportedFieldMediaRequest(FieldAttachmentRequest):
    external_id: str = Field(min_length=1, max_length=500)
