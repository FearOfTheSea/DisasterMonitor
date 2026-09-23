from dataclasses import replace
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
from disaster_monitor.infrastructure.field_reports.memory_store import (
    InMemoryFieldReportStore,
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


@pytest.mark.asyncio
async def test_field_store_does_not_publish_failed_json_write(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JsonFieldReportStore(tmp_path / "field-reports.json")
    report = await FieldReportService(store, clock=lambda: NOW).submit(
        NewFieldReport(
            report_type="flooding",
            text="Water covers the bridge.",
            captured_at=NOW,
            source_created_at=NOW,
            submitter_channel="operator-form",
            geometry=FieldReportGeometry(
                FieldReportGeometryKind.POINT,
                (FieldCoordinate(longitude=106.0, latitude=21.0),),
            ),
            location_precision=LocationPrecision.APPROXIMATE,
            location_uncertainty_m=100,
        )
    )

    def fail_write(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_persist", fail_write)
    with pytest.raises(OSError, match="disk full"):
        await store.add_report(replace(report, report_id="field-report:second"))
    assert await store.report("field-report:second") is None


@pytest.mark.asyncio
async def test_workspace_does_not_publish_failed_json_write(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JsonOperatorWorkspaceStore(tmp_path / "operator-workspace.json")
    service = OperatorWorkspaceService(store, clock=lambda: NOW)

    def fail_write(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_persist", fail_write)
    with pytest.raises(OSError, match="disk full"):
        await service.add_note(incident_id="event-1", text="Check source.")
    assert await store.notes("event-1") == ()


@pytest.mark.asyncio
async def test_import_capacity_failure_removes_media_and_keeps_batch_empty(
    tmp_path,
) -> None:
    source = FieldReportService(InMemoryFieldReportStore(), clock=lambda: NOW)
    base = await source.submit(
        NewFieldReport(
            report_type="flooding",
            text="Water covers a bridge.",
            captured_at=NOW,
            source_created_at=NOW,
            submitter_channel="operator-form",
            geometry=FieldReportGeometry(
                FieldReportGeometryKind.POINT,
                (FieldCoordinate(longitude=106.0, latitude=21.0),),
            ),
            location_precision=LocationPrecision.APPROXIMATE,
            location_uncertainty_m=100,
        )
    )
    privacy = FieldMediaPrivacyService(clock=lambda: NOW)
    media_store = FilesystemFieldMediaStore(tmp_path / "media", clock=lambda: NOW)
    service = FieldReportService(
        JsonFieldReportStore(tmp_path / "reports.json", maximum_reports=1),
        clock=lambda: NOW,
        privacy=privacy,
        media_store=media_store,
    )
    prepared = service.sanitize_media(
        filename="road.png",
        media_type="image/png",
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB\x60\x82",
    )
    first = replace(base, report_id="field-report:one", media=(prepared.lineage,))
    second = replace(base, report_id="field-report:two")

    with pytest.raises(ValueError, match="record limit"):
        await service.import_reports((first, second), (prepared,))

    assert await service.list_queue() == ()
    assert media_store.get(prepared.lineage.media_id) is None
    assert not tuple((tmp_path / "media").rglob("*.bin"))


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
