"""Untrusted field submissions and explicit human-review outcomes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from math import isfinite

from disaster_monitor.domain.disaster_types import _is_aware


class FieldReportGeometryKind(StrEnum):
    POINT = "point"
    POLYGON = "polygon"


class LocationPrecision(StrEnum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    UNKNOWN = "unknown"


class FieldReportReviewState(StrEnum):
    PENDING_REVIEW = "pending_review"
    RETAINED_UNVERIFIED = "retained_unverified"
    REJECTED = "rejected"
    ASSOCIATED = "associated"
    ADMITTED_OPERATOR_OBSERVATION = "admitted_operator_observation"


class FieldReportReviewDecision(StrEnum):
    REJECT = "reject"
    RETAIN_UNVERIFIED = "retain_unverified"
    ASSOCIATE_TO_EVENT = "associate_to_event"
    ADMIT_OPERATOR_OBSERVATION = "admit_operator_observation"


@dataclass(frozen=True, slots=True)
class FieldCoordinate:
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if not isfinite(self.longitude) or not isfinite(self.latitude):
            raise ValueError("Field-report coordinates must be finite.")
        if not -180 <= self.longitude <= 180 or not -90 <= self.latitude <= 90:
            raise ValueError("Field-report coordinates are outside WGS84 bounds.")


@dataclass(frozen=True, slots=True)
class FieldReportGeometry:
    kind: FieldReportGeometryKind
    coordinates: tuple[FieldCoordinate, ...]

    def __post_init__(self) -> None:
        if self.kind is FieldReportGeometryKind.POINT and len(self.coordinates) != 1:
            raise ValueError("Point field reports require exactly one coordinate.")
        if self.kind is FieldReportGeometryKind.POLYGON and (
            len(self.coordinates) < 4 or self.coordinates[0] != self.coordinates[-1]
        ):
            raise ValueError("Polygon field reports require a closed exterior ring.")

    @property
    def centroid(self) -> FieldCoordinate:
        points = (
            self.coordinates[:-1]
            if self.kind is FieldReportGeometryKind.POLYGON
            else self.coordinates
        )
        return FieldCoordinate(
            longitude=sum(point.longitude for point in points) / len(points),
            latitude=sum(point.latitude for point in points) / len(points),
        )


@dataclass(frozen=True, slots=True)
class FieldMediaLineage:
    media_id: str
    original_filename: str
    media_type: str
    original_sha256: str
    stored_sha256: str
    byte_length: int
    transformations: tuple[str, ...]
    retention_expires_at: datetime

    def __post_init__(self) -> None:
        if not self.media_id.strip() or not self.original_filename.strip():
            raise ValueError("Field media requires stable identity and filename.")
        if self.media_type not in {"image/jpeg", "image/png"}:
            raise ValueError("Field media is limited to JPEG and PNG images.")
        for checksum in (self.original_sha256, self.stored_sha256):
            if len(checksum) != 64 or any(
                character not in "0123456789abcdef" for character in checksum
            ):
                raise ValueError("Field media requires lowercase SHA-256 checksums.")
        if self.byte_length <= 0:
            raise ValueError("Field media must contain bytes.")
        if not self.transformations:
            raise ValueError("Field media transformations must be recorded.")
        if not _is_aware(self.retention_expires_at):
            raise ValueError("Field media retention time must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class FieldImportProvenance:
    import_id: str
    source_system: str
    source_record_id: str
    imported_at: datetime
    reviewed_by: str
    field_mapping: tuple[tuple[str, str], ...]
    external_verification: str | None
    verification_inherited: bool = False

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.import_id,
                self.source_system,
                self.source_record_id,
                self.reviewed_by,
            )
        ):
            raise ValueError("Field imports require source identity.")
        if not _is_aware(self.imported_at):
            raise ValueError("Field import time must be timezone-aware.")
        if self.verification_inherited:
            raise ValueError("External verification must never be inherited.")


@dataclass(frozen=True, slots=True)
class UnverifiedFieldReport:
    report_id: str
    report_type: str
    text: str
    captured_at: datetime
    source_created_at: datetime
    received_at: datetime
    submitter_channel: str
    geometry: FieldReportGeometry
    location_precision: LocationPrecision
    location_uncertainty_m: float | None
    media: tuple[FieldMediaLineage, ...]
    import_provenance: FieldImportProvenance | None
    review_state: FieldReportReviewState
    authority: str = "unverified"
    tags: tuple[str, ...] = ()
    associated_event_id: str | None = None
    review_revision: int = 0

    def __post_init__(self) -> None:
        if not self.report_id.strip() or not self.report_type.strip():
            raise ValueError("Field reports require identity and type.")
        if not self.text.strip():
            raise ValueError("Field reports require bounded report text.")
        if len(self.text) > 10_000:
            raise ValueError("Field-report text exceeds the bounded limit.")
        if not isinstance(self.captured_at, datetime) or not _is_aware(
            self.captured_at
        ):
            raise ValueError("Field reports require an aware capture time.")
        if not isinstance(self.source_created_at, datetime) or not _is_aware(
            self.source_created_at
        ):
            raise ValueError("Field reports require an aware source time.")
        if not isinstance(self.received_at, datetime) or not _is_aware(
            self.received_at
        ):
            raise ValueError("Field reports require an aware receipt time.")
        if self.source_created_at > self.received_at:
            raise ValueError("Field-report source time cannot follow receipt time.")
        if not self.submitter_channel.strip():
            raise ValueError("Field reports require a submitter channel.")
        if self.authority != "unverified":
            raise ValueError("Field reports must retain unverified authority.")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("Field-report tags must not be empty.")
        if self.location_precision is LocationPrecision.EXACT:
            if self.location_uncertainty_m not in {None, 0}:
                raise ValueError(
                    "Exact locations cannot declare an uncertainty radius."
                )
        elif self.location_precision is LocationPrecision.APPROXIMATE:
            if (
                self.location_uncertainty_m is None
                or not isfinite(self.location_uncertainty_m)
                or self.location_uncertainty_m <= 0
            ):
                raise ValueError("Approximate locations require an uncertainty radius.")
        elif self.location_uncertainty_m is not None:
            raise ValueError("Unknown locations cannot assert an uncertainty radius.")
        associated_states = {
            FieldReportReviewState.ASSOCIATED,
            FieldReportReviewState.ADMITTED_OPERATOR_OBSERVATION,
        }
        if (self.review_state in associated_states) != bool(self.associated_event_id):
            raise ValueError("Associated review states require exactly one event ID.")
        if self.review_revision < 0:
            raise ValueError("Field-report review revisions cannot be negative.")


@dataclass(frozen=True, slots=True)
class FieldReportReview:
    review_id: str
    report_id: str
    decision: FieldReportReviewDecision
    reviewer_id: str
    rationale: str
    reviewed_at: datetime
    event_id: str | None
    authority_policy_id: str | None
    revision: int

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.review_id, self.report_id, self.reviewer_id)
        ):
            raise ValueError("Field-report reviews require stable identity.")
        if not self.rationale.strip() or len(self.rationale) > 2_000:
            raise ValueError("Field-report reviews require a bounded rationale.")
        if not _is_aware(self.reviewed_at):
            raise ValueError("Field-report review time must be timezone-aware.")
        needs_event = self.decision in {
            FieldReportReviewDecision.ASSOCIATE_TO_EVENT,
            FieldReportReviewDecision.ADMIT_OPERATOR_OBSERVATION,
        }
        if needs_event != bool(self.event_id):
            raise ValueError("This field-report review decision requires an event ID.")
        needs_policy = (
            self.decision is FieldReportReviewDecision.ADMIT_OPERATOR_OBSERVATION
        )
        if needs_policy != bool(self.authority_policy_id):
            raise ValueError(
                "Operator-observation admission requires an authority policy."
            )


@dataclass(frozen=True, slots=True)
class OperatorObservation:
    observation_id: str
    source_report_id: str
    event_id: str
    admitted_at: datetime
    admitted_by: str
    authority_policy_id: str
    authority: str = "operator_observation"


@dataclass(frozen=True, slots=True)
class FieldReportReviewOutcome:
    report: UnverifiedFieldReport
    review: FieldReportReview
    operator_observation: OperatorObservation | None


@dataclass(frozen=True, slots=True)
class FieldReportDuplicateCandidate:
    candidate_id: str
    report_ids: tuple[str, str]
    time_delta_seconds: float
    distance_km: float
    same_type: bool
    score: float
    auto_merge: bool = False


def apply_field_report_review(
    report: UnverifiedFieldReport, review: FieldReportReview
) -> UnverifiedFieldReport:
    if review.report_id != report.report_id:
        raise ValueError("Field-report review targets a different report.")
    if review.revision != report.review_revision + 1:
        raise ValueError("Field-report review revision is stale.")
    states = {
        FieldReportReviewDecision.REJECT: FieldReportReviewState.REJECTED,
        FieldReportReviewDecision.RETAIN_UNVERIFIED: (
            FieldReportReviewState.RETAINED_UNVERIFIED
        ),
        FieldReportReviewDecision.ASSOCIATE_TO_EVENT: (
            FieldReportReviewState.ASSOCIATED
        ),
        FieldReportReviewDecision.ADMIT_OPERATOR_OBSERVATION: (
            FieldReportReviewState.ADMITTED_OPERATOR_OBSERVATION
        ),
    }
    return replace(
        report,
        review_state=states[review.decision],
        associated_event_id=review.event_id,
        review_revision=review.revision,
    )
