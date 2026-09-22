from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from disaster_monitor.application.field_reports.duplicates import (
    FieldReportDuplicateDetector,
)
from disaster_monitor.application.field_reports.media_privacy import (
    FieldMediaPrivacyService,
    SensitiveFieldContentError,
)
from disaster_monitor.application.field_reports.service import (
    FieldReportService,
    NewFieldReport,
)
from disaster_monitor.domain.field_reports import (
    FieldCoordinate,
    FieldMediaLineage,
    FieldReportGeometry,
    FieldReportGeometryKind,
    FieldReportReviewDecision,
    FieldReportReviewState,
    LocationPrecision,
    UnverifiedFieldReport,
)
from disaster_monitor.infrastructure.field_reports.memory_store import (
    InMemoryFieldReportStore,
)

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)


def _report(
    report_id: str,
    *,
    longitude: float = 106.0,
    captured_at: datetime = NOW,
    report_type: str = "road_blocked",
) -> UnverifiedFieldReport:
    return UnverifiedFieldReport(
        report_id=report_id,
        report_type=report_type,
        text="Water is covering the road near the bridge.",
        captured_at=captured_at,
        source_created_at=captured_at - timedelta(minutes=2),
        received_at=max(NOW, captured_at + timedelta(minutes=1)),
        submitter_channel="operator-form",
        geometry=FieldReportGeometry(
            FieldReportGeometryKind.POINT,
            (FieldCoordinate(longitude=longitude, latitude=21.0),),
        ),
        location_precision=LocationPrecision.APPROXIMATE,
        location_uncertainty_m=250,
        media=(),
        import_provenance=None,
        review_state=FieldReportReviewState.PENDING_REVIEW,
        authority="unverified",
    )


def test_unverified_field_report_requires_provenance_and_uncertainty() -> None:
    with pytest.raises(ValueError, match="source time"):
        UnverifiedFieldReport(
            report_id="report:bad",
            report_type="flooding",
            text="Flooding reported.",
            captured_at=NOW,
            source_created_at=None,  # type: ignore[arg-type]
            received_at=NOW,
            submitter_channel="operator-form",
            geometry=FieldReportGeometry(
                FieldReportGeometryKind.POINT,
                (FieldCoordinate(longitude=106, latitude=21),),
            ),
            location_precision=LocationPrecision.APPROXIMATE,
            location_uncertainty_m=100,
            media=(),
            import_provenance=None,
            review_state=FieldReportReviewState.PENDING_REVIEW,
            authority="unverified",
        )

    with pytest.raises(ValueError, match="unverified"):
        replace(_report("report:bad-authority"), authority="official")


def test_duplicate_detection_only_proposes_review_candidates() -> None:
    detector = FieldReportDuplicateDetector(
        maximum_time_delta=timedelta(hours=6), maximum_distance_km=10
    )
    candidates = detector.detect(
        (
            _report("report:one"),
            _report(
                "report:two",
                longitude=106.02,
                captured_at=NOW + timedelta(minutes=15),
            ),
            _report("report:far", longitude=108),
        )
    )

    assert len(candidates) == 1
    assert candidates[0].report_ids == ("report:one", "report:two")
    assert candidates[0].auto_merge is False
    assert all(
        report.review_state is FieldReportReviewState.PENDING_REVIEW
        for report in (
            _report("report:one"),
            _report("report:two"),
        )
    )


@pytest.mark.asyncio
async def test_human_review_has_explicit_non_promoting_and_operator_paths() -> None:
    store = InMemoryFieldReportStore()
    service = FieldReportService(store, clock=lambda: NOW)
    report = await service.submit(
        NewFieldReport(
            report_type="flooding",
            text="Floodwater is visible beside a marked road.",
            captured_at=NOW - timedelta(minutes=5),
            source_created_at=NOW - timedelta(minutes=10),
            submitter_channel="operator-form",
            geometry=FieldReportGeometry(
                FieldReportGeometryKind.POINT,
                (FieldCoordinate(longitude=106, latitude=21),),
            ),
            location_precision=LocationPrecision.APPROXIMATE,
            location_uncertainty_m=100,
        )
    )

    retained = await service.review(
        report.report_id,
        FieldReportReviewDecision.RETAIN_UNVERIFIED,
        reviewer_id="operator:local",
        rationale="The report is relevant but not independently verified.",
    )
    assert retained.report.review_state is FieldReportReviewState.RETAINED_UNVERIFIED
    assert retained.operator_observation is None

    associated = await service.review(
        report.report_id,
        FieldReportReviewDecision.ASSOCIATE_TO_EVENT,
        reviewer_id="operator:local",
        rationale="The location and time overlap the selected incident.",
        event_id="event-1",
    )
    assert associated.report.review_state is FieldReportReviewState.ASSOCIATED
    assert associated.report.associated_event_id == "event-1"
    assert associated.operator_observation is None

    admitted = await service.review(
        report.report_id,
        FieldReportReviewDecision.ADMIT_OPERATOR_OBSERVATION,
        reviewer_id="operator:local",
        rationale="A trusted operator reviewed the original capture and provenance.",
        event_id="event-1",
        authority_policy_id="operator-observation-admission.v1",
    )
    assert admitted.operator_observation is not None
    assert admitted.operator_observation.authority == "operator_observation"
    assert admitted.operator_observation.source_report_id == report.report_id


def test_field_media_strips_jpeg_exif_and_blocks_secret_bearing_text() -> None:
    original = (
        b"\xff\xd8"
        + b"\xff\xe1\x00\x12Exif\x00\x00GPS SECRET"
        + b"\xff\xdb\x00\x04xx"
        + b"\xff\xd9"
    )
    service = FieldMediaPrivacyService(clock=lambda: NOW, retention_days=30)
    result = service.sanitize(
        filename="road.jpg", media_type="image/jpeg", content=original
    )

    assert b"Exif" not in result.content
    assert result.lineage.original_sha256 == sha256(original).hexdigest()
    assert result.lineage.stored_sha256 == sha256(result.content).hexdigest()
    assert "stripped-jpeg-app1-exif" in result.lineage.transformations
    assert result.lineage.retention_expires_at == NOW + timedelta(days=30)

    with pytest.raises(SensitiveFieldContentError, match="secret"):
        service.validate_report_text("token=sk-test-secret-value-123456789")


def test_media_lineage_requires_recorded_transformation_and_retention() -> None:
    with pytest.raises(ValueError, match="transformations"):
        FieldMediaLineage(
            media_id="media:one",
            original_filename="road.jpg",
            media_type="image/jpeg",
            original_sha256="a" * 64,
            stored_sha256="b" * 64,
            byte_length=100,
            transformations=(),
            retention_expires_at=NOW + timedelta(days=30),
        )


@pytest.mark.asyncio
async def test_import_privacy_validation_is_atomic_before_report_persistence() -> None:
    store = InMemoryFieldReportStore()
    service = FieldReportService(
        store,
        privacy=FieldMediaPrivacyService(clock=lambda: NOW),
        clock=lambda: NOW,
    )
    safe = _report("report:safe")
    sensitive = replace(
        _report("report:sensitive"),
        text="Contact field coordinator at person@example.test.",
    )

    with pytest.raises(SensitiveFieldContentError, match="PII"):
        await service.import_reports((safe, sensitive))

    assert await service.list_queue() == ()
