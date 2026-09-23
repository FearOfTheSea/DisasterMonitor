import base64
from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.field_reports.media_privacy import (
    FieldMediaPrivacyService,
)
from disaster_monitor.application.field_reports.service import FieldReportService
from disaster_monitor.application.humanitarian.context import HumanitarianContextService
from disaster_monitor.application.operator_workspace.service import (
    OperatorWorkspaceService,
)
from disaster_monitor.application.ports.operator_identity import (
    TrustedOperatorIdentityPolicy,
)
from disaster_monitor.infrastructure.field_reports.filesystem_media_store import (
    FilesystemFieldMediaStore,
)
from disaster_monitor.infrastructure.field_reports.memory_store import (
    InMemoryFieldReportStore,
)
from disaster_monitor.infrastructure.operator_workspace.memory_store import (
    InMemoryOperatorWorkspaceStore,
)
from disaster_monitor.presentation.http.api import create_http_app
from disaster_monitor.presentation.http.field_report_routes import (
    get_field_report_service,
    get_humanitarian_context_service,
    get_operator_workspace_service,
)
from disaster_monitor.presentation.http.operator_identity import (
    get_trusted_operator_identity_policy,
)

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)
OPERATOR_HEADERS = {"x-test-operator": "operator:local"}


class ExistingIncidentVerifier:
    async def exists(self, event_id: str) -> bool:
        return event_id == "event-1"


@pytest.fixture
def app(tmp_path):
    result = create_http_app(title="test")
    field_reports = FieldReportService(
        InMemoryFieldReportStore(),
        clock=lambda: NOW,
        privacy=FieldMediaPrivacyService(clock=lambda: NOW),
        media_store=FilesystemFieldMediaStore(tmp_path / "media"),
        event_verifier=ExistingIncidentVerifier(),
    )
    operator_workspace = OperatorWorkspaceService(
        InMemoryOperatorWorkspaceStore(), clock=lambda: NOW
    )
    result.dependency_overrides[get_field_report_service] = lambda: field_reports
    result.dependency_overrides[get_operator_workspace_service] = lambda: (
        operator_workspace
    )
    result.dependency_overrides[get_humanitarian_context_service] = lambda: (
        HumanitarianContextService(clock=lambda: NOW)
    )
    result.dependency_overrides[get_trusted_operator_identity_policy] = lambda: (
        TrustedOperatorIdentityPolicy(enabled=True, header_name="x-test-operator")
    )
    return result


@pytest.mark.asyncio
async def test_operator_submits_and_reviews_unverified_field_report(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/field-reports",
            json={
                "report_type": "flooding",
                "text": "Water is visible over the marked road.",
                "captured_at": "2026-09-16T07:45:00Z",
                "source_created_at": "2026-09-16T07:50:00Z",
                "submitter_channel": "operator-form",
                "geometry": {
                    "type": "Point",
                    "coordinates": [106.0, 21.0],
                },
                "location_precision": "approximate",
                "location_uncertainty_m": 100,
                "attachments": [],
            },
        )
        assert response.status_code == 201
        report = response.json()
        assert report["authority"] == "unverified"
        assert report["review_state"] == "pending_review"

        queued = await client.get("/api/v1/field-reports")
        assert queued.status_code == 200
        assert queued.json()[0]["report_id"] == report["report_id"]

        reviewed = await client.post(
            f"/api/v1/field-reports/{report['report_id']}/reviews",
            headers=OPERATOR_HEADERS,
            json={
                "decision": "associate_to_event",
                "rationale": "Time and location overlap the selected event.",
                "event_id": "event-1",
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["report"]["review_state"] == "associated"
        assert reviewed.json()["operator_observation"] is None


@pytest.mark.asyncio
async def test_review_requires_trusted_identity_and_existing_event(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        submitted = await client.post(
            "/api/v1/field-reports",
            json={
                "report_type": "flooding",
                "text": "Water covers the road.",
                "captured_at": "2026-09-16T07:45:00Z",
                "source_created_at": "2026-09-16T07:50:00Z",
                "submitter_channel": "operator-form",
                "geometry": {"type": "Point", "coordinates": [106.0, 21.0]},
                "location_precision": "approximate",
                "location_uncertainty_m": 100,
            },
        )
        report_id = submitted.json()["report_id"]
        path = f"/api/v1/field-reports/{report_id}/reviews"
        review = {
            "decision": "admit_operator_observation",
            "rationale": "Verified against the source record.",
            "event_id": "event-1",
            "authority_policy_id": "operator-observation-admission.v1",
        }
        assert (await client.post(path, json=review)).status_code == 401
        assert (
            await client.post(
                path,
                headers=OPERATOR_HEADERS,
                json={**review, "reviewer_id": "forged"},
            )
        ).status_code == 422
        assert (
            await client.post(
                path,
                headers=OPERATOR_HEADERS,
                json={**review, "event_id": "missing"},
            )
        ).status_code == 404
        admitted = await client.post(path, headers=OPERATOR_HEADERS, json=review)
        assert admitted.status_code == 200
        assert admitted.json()["review"]["reviewer_id"] == "operator:local"


@pytest.mark.asyncio
async def test_field_report_attachment_is_sanitized_before_persistence(app) -> None:
    jpeg = b"\xff\xd8\xff\xe1\x00\x12Exif\x00\x00GPS SECRET\xff\xd9"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/field-reports",
            json={
                "report_type": "access",
                "text": "A road obstruction was reported.",
                "captured_at": "2026-09-16T07:45:00Z",
                "source_created_at": "2026-09-16T07:50:00Z",
                "submitter_channel": "operator-form",
                "geometry": {
                    "type": "Point",
                    "coordinates": [106.0, 21.0],
                },
                "location_precision": "approximate",
                "location_uncertainty_m": 100,
                "attachments": [
                    {
                        "filename": "road.jpg",
                        "media_type": "image/jpeg",
                        "content_base64": base64.b64encode(jpeg).decode(),
                    }
                ],
            },
        )
    assert response.status_code == 201
    assert response.json()["media"][0]["transformations"][0] == (
        "stripped-jpeg-app1-exif"
    )


@pytest.mark.asyncio
async def test_rejected_report_does_not_leave_media(app, tmp_path) -> None:
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB\x60\x82"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/field-reports",
            json={
                "report_type": "flooding",
                "text": "Contact person@example.test about flooding.",
                "captured_at": "2026-09-16T07:45:00Z",
                "source_created_at": "2026-09-16T07:50:00Z",
                "submitter_channel": "operator-form",
                "geometry": {"type": "Point", "coordinates": [106.0, 21.0]},
                "location_precision": "approximate",
                "location_uncertainty_m": 100,
                "attachments": [
                    {
                        "filename": "road.png",
                        "media_type": "image/png",
                        "content_base64": base64.b64encode(png).decode(),
                    }
                ],
            },
        )
    assert response.status_code == 422
    assert not tuple((tmp_path / "media").rglob("*.bin"))


@pytest.mark.asyncio
async def test_exact_retry_returns_existing_report_and_conflicting_retry_is_rejected(
    app,
) -> None:
    body = {
        "report_type": "flooding",
        "text": "Water covers the lower road.",
        "captured_at": "2026-09-16T07:45:00Z",
        "source_created_at": "2026-09-16T07:50:00Z",
        "submitter_channel": "operator-form",
        "geometry": {"type": "Point", "coordinates": [106.0, 21.0]},
        "location_precision": "approximate",
        "location_uncertainty_m": 100,
        "attachments": [],
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/field-reports", json=body)
        retry = await client.post("/api/v1/field-reports", json=body)
        conflict = await client.post(
            "/api/v1/field-reports",
            json={**body, "location_uncertainty_m": 200},
        )
    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_field_report_body_limit_rejects_oversized_requests(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/field-reports/imports",
            content=b"x" * (52 * 1024 * 1024 + 1),
        )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_operator_workspace_routes_label_notes_as_non_evidence(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/operator-workspace/notes",
            json={
                "incident_id": "event-1",
                "text": "Confirm source revision before briefing.",
                "tags": ["briefing"],
            },
        )
        assert response.status_code == 201
        assert response.json()["evidence"] is False

        exported = await client.get(
            "/api/v1/operator-workspace", params={"incident_id": "event-1"}
        )
        assert exported.status_code == 200
        assert exported.json()["boundary"] == "non_evidence_operator_state"


@pytest.mark.asyncio
async def test_case_notebook_routes_keep_research_out_of_evidence(app) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/operator-workspace/notebooks",
            json={
                "title": "Flood chronology review",
                "created_by": "operator:local",
                "incident_ids": ["event-1"],
            },
        )
        assert created.status_code == 201
        assert created.json()["evidence"] is False
        notebook_id = created.json()["notebook_id"]

        entry = await client.post(
            f"/api/v1/operator-workspace/notebooks/{notebook_id}/entries",
            json={
                "kind": "source_snapshot",
                "title": "Initial bulletin",
                "content": "Pinned for later comparison.",
                "reference_id": "snapshot:one",
                "created_by": "operator:local",
            },
        )
        assert entry.status_code == 201
        assert entry.json()["evidence"] is False
        assert entry.json()["alters_canonical_state"] is False

        entries = await client.get(
            f"/api/v1/operator-workspace/notebooks/{notebook_id}/entries"
        )
        assert entries.status_code == 200
        assert entries.json()[0]["reference_id"] == "snapshot:one"

        missing = await client.get(
            "/api/v1/operator-workspace/notebooks/missing/entries"
        )
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_reviewed_kobo_import_preserves_mapping_and_sanitized_media(app) -> None:
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB\x60\x82"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/field-reports/imports",
            headers=OPERATOR_HEADERS,
            json={
                "source_system": "kobotoolbox",
                "format": "csv",
                "content": (
                    "id,kind,details,captured,created,lat,lon,verified\n"
                    "row-1,flooding,Water near bridge,2026-09-15T07:00:00Z,"
                    "2026-09-15T07:05:00Z,21.0,106.0,true\n"
                ),
                "mapping": {
                    "external_id": "id",
                    "report_type": "kind",
                    "text": "details",
                    "captured_at": "captured",
                    "source_created_at": "created",
                    "latitude": "lat",
                    "longitude": "lon",
                    "external_verification": "verified",
                },
                "media_packages": [
                    {
                        "external_id": "row-1",
                        "filename": "field.png",
                        "media_type": "image/png",
                        "content_base64": base64.b64encode(png).decode(),
                    }
                ],
            },
        )

        assert response.status_code == 201
        imported = response.json()["reports"][0]
        assert imported["authority"] == "unverified"
        assert imported["import_provenance"]["reviewed_by"] == "operator:local"
        assert imported["import_provenance"]["verification_inherited"] is False
        assert imported["media"][0]["transformations"][0] == (
            "verified-no-png-metadata"
        )

        exported = await client.get("/api/v1/field-reports/ushahidi-export")
        assert exported.status_code == 200
        assert exported.json()["results"][0]["verification_status"] == (
            "unverified_by_disastermonitor"
        )
