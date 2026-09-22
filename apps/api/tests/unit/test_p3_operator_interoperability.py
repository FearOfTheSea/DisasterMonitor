import json
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest

from disaster_monitor.application.field_reports.importers import (
    ExternalFieldMapping,
    FieldReportImportService,
    UshahidiMapper,
)
from disaster_monitor.application.interoperability.collaboration import (
    build_mapping_workflow_package,
)
from disaster_monitor.application.interoperability.evidence_packages import (
    EvidencePackageBuilder,
    EvidencePackageVerificationError,
    EvidencePackageVerifier,
)
from disaster_monitor.application.operator_workspace.service import (
    OperatorWorkspaceService,
)
from disaster_monitor.domain.field_reports import FieldReportReviewState
from disaster_monitor.infrastructure.operator_workspace.memory_store import (
    InMemoryOperatorWorkspaceStore,
)

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)


def test_kobo_odk_csv_import_requires_mapping_and_never_inherits_verification() -> None:
    service = FieldReportImportService(clock=lambda: NOW)
    csv_text = (
        "submission_id,kind,details,when,created,latitude,longitude,verified\n"
        "row-1,flooding,Water near bridge,2026-09-16T07:00:00Z,"
        "2026-09-16T07:05:00Z,21.0,106.0,true\n"
    )
    result = service.import_csv(
        csv_text,
        source_system="kobotoolbox",
        reviewed_by="operator:local",
        mapping=ExternalFieldMapping(
            external_id="submission_id",
            report_type="kind",
            text="details",
            captured_at="when",
            source_created_at="created",
            latitude="latitude",
            longitude="longitude",
            external_verification="verified",
        ),
    )

    assert len(result.reports) == 1
    report = result.reports[0]
    assert report.review_state is FieldReportReviewState.PENDING_REVIEW
    assert report.authority == "unverified"
    assert report.import_provenance is not None
    assert report.import_provenance.reviewed_by == "operator:local"
    assert report.import_provenance.external_verification == "true"
    assert report.import_provenance.verification_inherited is False


def test_ushahidi_mapping_round_trips_as_unverified() -> None:
    mapper = UshahidiMapper(clock=lambda: NOW)
    imported = mapper.import_posts(
        {
            "results": [
                {
                    "id": 42,
                    "title": "Bridge access",
                    "content": "Road is reportedly blocked.",
                    "created": "2026-09-16T07:00:00Z",
                    "status": "published",
                    "categories": ["access"],
                    "geometry": {"type": "Point", "coordinates": [106, 21]},
                }
            ]
        },
        reviewed_by="operator:local",
    )
    exported = mapper.export_posts(imported.reports)

    assert imported.reports[0].authority == "unverified"
    assert exported["results"][0]["verification_status"] == (
        "unverified_by_disastermonitor"
    )
    assert exported["results"][0]["categories"] == ["access"]


@pytest.mark.asyncio
async def test_notes_bookmarks_and_runbooks_are_explicitly_non_evidence() -> None:
    service = OperatorWorkspaceService(
        InMemoryOperatorWorkspaceStore(), clock=lambda: NOW
    )
    note = await service.add_note(
        incident_id="event-1",
        text="Call the regional desk before the next briefing.",
        tags=("handoff", "priority"),
    )
    bookmark = await service.add_bookmark(
        incident_id="event-1",
        target_type="source",
        target_id="source:snapshot-1",
        label="Latest situation report",
    )
    runbook = await service.create_runbook_template(
        name="Evidence review",
        steps=(
            "Inspect evidence finding:claim-1",
            "Record unresolved source gaps",
        ),
    )

    assert note.evidence is False
    assert bookmark.evidence is False
    assert runbook.autonomous_actions is False
    exported = await service.export_state(incident_id="event-1")
    assert exported["boundary"] == "non_evidence_operator_state"


def test_mapping_workflow_package_exports_aoi_without_creating_external_tasks() -> None:
    package = build_mapping_workflow_package(
        incident_id="event-1",
        aoi={
            "type": "Polygon",
            "coordinates": [[[106, 21], [107, 21], [107, 22], [106, 21]]],
        },
    )

    assert package.hot_tasking_manager_url.startswith("https://tasks.hotosm.org/")
    assert package.mapswipe_url.startswith("https://mapswipe.org/")
    assert package.external_task_created is False
    assert package.aoi_geojson["features"][0]["properties"]["incidentId"] == ("event-1")


def test_evidence_package_round_trip_verifies_checksums_and_stays_historical() -> None:
    builder = EvidencePackageBuilder(clock=lambda: NOW)
    archive = builder.build(
        incident_id="event-1",
        incident_snapshot={"event_id": "event-1", "status": "ongoing"},
        source_links=("https://example.test/source",),
        normalized_data={"claims": [{"id": "claim-1", "value": "5"}]},
        findings=({"finding_id": "finding-1"},),
        imagery_manifests=({"artifact_id": "image-1", "sha256": "a" * 64},),
        software_version="0.1.0",
        policy_versions=("evidence-reconciliation.v1",),
    )
    verified = EvidencePackageVerifier().verify(archive)

    assert verified.incident_id == "event-1"
    assert verified.external is True
    assert verified.historical is True
    assert verified.merge_into_live_state is False
    assert set(verified.verified_files) >= {
        "incident.json",
        "normalized-data.json",
        "findings.json",
        "imagery-manifests.json",
    }

    source = BytesIO(archive)
    target = BytesIO()
    with ZipFile(source) as current, ZipFile(target, "w") as changed:
        for name in current.namelist():
            content = current.read(name)
            changed.writestr(name, b"{}" if name == "incident.json" else content)
    with pytest.raises(EvidencePackageVerificationError, match="checksum"):
        EvidencePackageVerifier().verify(target.getvalue())


def test_evidence_package_manifest_is_deterministic_json() -> None:
    archive = EvidencePackageBuilder(clock=lambda: NOW).build(
        incident_id="event-1",
        incident_snapshot={"event_id": "event-1"},
        source_links=(),
        normalized_data={},
        findings=(),
        imagery_manifests=(),
        software_version="0.1.0",
        policy_versions=(),
    )
    with ZipFile(BytesIO(archive)) as package:
        manifest = json.loads(package.read("manifest.json"))
    assert manifest["schema_version"] == "disastermonitor-evidence-package.v1"
    assert manifest["classification"] == "bounded_incident_snapshot"


def test_evidence_package_builder_rejects_inconsistent_incident_identity() -> None:
    with pytest.raises(ValueError, match="incident identity"):
        EvidencePackageBuilder(clock=lambda: NOW).build(
            incident_id="event-1",
            incident_snapshot={"event_id": "event-2"},
            source_links=(),
            normalized_data={},
            findings=(),
            imagery_manifests=(),
            software_version="0.1.0",
            policy_versions=(),
        )


def test_evidence_package_rejects_undeclared_files_and_expansion_bombs() -> None:
    builder = EvidencePackageBuilder(clock=lambda: NOW)
    archive = builder.build(
        incident_id="event-1",
        incident_snapshot={"event_id": "event-1"},
        source_links=(),
        normalized_data={"padding": "x" * 100_000},
        findings=(),
        imagery_manifests=(),
        software_version="0.1.0",
        policy_versions=(),
    )
    source = BytesIO(archive)
    target = BytesIO()
    with ZipFile(source) as current, ZipFile(target, "w") as changed:
        for name in current.namelist():
            changed.writestr(name, current.read(name))
        changed.writestr("undeclared.json", b"{}")

    with pytest.raises(EvidencePackageVerificationError, match="undeclared"):
        EvidencePackageVerifier().verify(target.getvalue())
    with pytest.raises(EvidencePackageVerificationError, match="expanded"):
        EvidencePackageVerifier(maximum_bytes=5_000).verify(archive)


def test_evidence_package_rejects_checksum_valid_invalid_json_payload() -> None:
    archive = EvidencePackageBuilder(clock=lambda: NOW).build(
        incident_id="event-1",
        incident_snapshot={"event_id": "event-1"},
        source_links=(),
        normalized_data={},
        findings=(),
        imagery_manifests=(),
        software_version="0.1.0",
        policy_versions=(),
    )
    source = BytesIO(archive)
    target = BytesIO()
    replacement = b"not-json"
    with ZipFile(source) as current:
        manifest = json.loads(current.read("manifest.json"))
        for item in manifest["files"]:
            if item["path"] == "incident.json":
                item["sha256"] = sha256(replacement).hexdigest()
                item["bytes"] = len(replacement)
        with ZipFile(target, "w") as changed:
            for name in current.namelist():
                content = (
                    json.dumps(manifest).encode()
                    if name == "manifest.json"
                    else replacement
                    if name == "incident.json"
                    else current.read(name)
                )
                changed.writestr(name, content)

    with pytest.raises(EvidencePackageVerificationError, match="JSON payload"):
        EvidencePackageVerifier().verify(target.getvalue())
