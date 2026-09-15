from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.field_reports.media_privacy import (
    FieldMediaPrivacyService,
)
from disaster_monitor.application.field_reports.service import (
    FieldReportService,
    NewFieldReport,
)
from disaster_monitor.application.operator_workspace.service import (
    OperatorWorkspaceService,
)
from disaster_monitor.domain.field_reports import (
    FieldCoordinate,
    FieldReportGeometry,
    FieldReportGeometryKind,
    FieldReportReviewDecision,
    LocationPrecision,
)
from disaster_monitor.infrastructure.field_reports.filesystem_media_store import (
    FilesystemFieldMediaStore,
)
from disaster_monitor.infrastructure.field_reports.json_store import (
    JsonFieldReportStore,
)
from disaster_monitor.infrastructure.operator_workspace.json_store import (
    JsonOperatorWorkspaceStore,
)

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_field_reports_and_reviews_survive_store_reconstruction(tmp_path) -> None:
    path = tmp_path / "field-reports.json"
    service = FieldReportService(JsonFieldReportStore(path), clock=lambda: NOW)
    report = await service.submit(
        NewFieldReport(
            report_type="road_blocked",
            text="Water is covering the road beside the bridge.",
            captured_at=NOW - timedelta(minutes=10),
            source_created_at=NOW - timedelta(minutes=5),
            submitter_channel="operator-form",
            geometry=FieldReportGeometry(
                FieldReportGeometryKind.POINT,
                (FieldCoordinate(longitude=106.0, latitude=21.0),),
            ),
            location_precision=LocationPrecision.APPROXIMATE,
            location_uncertainty_m=100,
        )
    )
    await service.review(
        report.report_id,
        FieldReportReviewDecision.RETAIN_UNVERIFIED,
        reviewer_id="operator:local",
        rationale="Useful context without independent verification.",
    )

    restored = FieldReportService(JsonFieldReportStore(path), clock=lambda: NOW)
    queue = await restored.list_queue()

    assert queue == ((await service.list_queue())[0],)


@pytest.mark.asyncio
async def test_non_evidence_workspace_survives_store_reconstruction(tmp_path) -> None:
    path = tmp_path / "operator-workspace.json"
    service = OperatorWorkspaceService(
        JsonOperatorWorkspaceStore(path), clock=lambda: NOW
    )
    note = await service.add_note(
        incident_id="event-1",
        text="Confirm the road report with the district desk.",
        tags=("handoff",),
    )
    await service.add_bookmark(
        incident_id="event-1",
        target_type="field_report",
        target_id="field-report:one",
        label="Needs review",
    )

    restored = OperatorWorkspaceService(
        JsonOperatorWorkspaceStore(path), clock=lambda: NOW
    )
    state = await restored.export_state(incident_id="event-1")

    assert state["notes"] == (note,)
    assert len(state["bookmarks"]) == 1
    assert state["boundary"] == "non_evidence_operator_state"


def test_expired_field_media_is_deleted_and_not_returned(tmp_path) -> None:
    admitted_at = NOW - timedelta(days=2)
    privacy = FieldMediaPrivacyService(clock=lambda: admitted_at, retention_days=1)
    sanitized = privacy.sanitize(
        filename="road.png",
        media_type="image/png",
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB\x60\x82",
    )
    store = FilesystemFieldMediaStore(tmp_path, clock=lambda: admitted_at)
    store.put(sanitized.lineage, sanitized.content)
    assert store.get(sanitized.lineage.media_id) is not None

    expired_store = FilesystemFieldMediaStore(tmp_path, clock=lambda: NOW)

    assert expired_store.get(sanitized.lineage.media_id) is None
    assert not tuple(tmp_path.rglob("*.bin"))


def test_invalid_field_media_retention_metadata_fails_closed(tmp_path) -> None:
    privacy = FieldMediaPrivacyService(clock=lambda: NOW, retention_days=1)
    sanitized = privacy.sanitize(
        filename="road.png",
        media_type="image/png",
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB\x60\x82",
    )
    store = FilesystemFieldMediaStore(tmp_path, clock=lambda: NOW)
    store.put(sanitized.lineage, sanitized.content)
    metadata_path = next(tmp_path.rglob("*.json"))
    metadata_path.write_text(
        '{"schema_version":"field-media-lineage.v1",'
        f'"media_id":"{sanitized.lineage.media_id}",'
        '"media_type":"image/png","retention_expires_at":"invalid"}',
        encoding="utf-8",
    )

    assert store.get(sanitized.lineage.media_id) is None
    assert not tuple(tmp_path.rglob("*.bin"))
