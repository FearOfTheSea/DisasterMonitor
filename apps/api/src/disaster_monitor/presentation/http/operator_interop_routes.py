"""HTTP boundary for operator state and shareable verification packages."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

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
from disaster_monitor.domain.operator_workspace import NotebookEntryKind
from disaster_monitor.presentation.http.field_report_routes import (
    get_operator_workspace_service,
)
from disaster_monitor.presentation.http.operator_interop_schemas import (
    AnalystNoteRequest,
    BookmarkRequest,
    CaseNotebookRequest,
    EvidencePackageCreateRequest,
    EvidencePackageVerifyRequest,
    MappingWorkflowRequest,
    NotebookEntryRequest,
    RunbookTemplateRequest,
)

router = APIRouter()


@router.post(
    "/operator-workspace/notes",
    tags=["operator-workspace"],
    status_code=status.HTTP_201_CREATED,
)
async def add_analyst_note(
    body: AnalystNoteRequest,
    service: Annotated[
        OperatorWorkspaceService, Depends(get_operator_workspace_service)
    ],
) -> dict[str, object]:
    try:
        return asdict(
            await service.add_note(
                incident_id=body.incident_id,
                text=body.text,
                tags=tuple(body.tags),
            )
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/operator-workspace/bookmarks",
    tags=["operator-workspace"],
    status_code=status.HTTP_201_CREATED,
)
async def add_bookmark(
    body: BookmarkRequest,
    service: Annotated[
        OperatorWorkspaceService, Depends(get_operator_workspace_service)
    ],
) -> dict[str, object]:
    try:
        return asdict(
            await service.add_bookmark(
                incident_id=body.incident_id,
                target_type=body.target_type,
                target_id=body.target_id,
                label=body.label,
            )
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/operator-workspace/runbooks",
    tags=["operator-workspace"],
    status_code=status.HTTP_201_CREATED,
)
async def add_runbook(
    body: RunbookTemplateRequest,
    service: Annotated[
        OperatorWorkspaceService, Depends(get_operator_workspace_service)
    ],
) -> dict[str, object]:
    try:
        return asdict(
            await service.create_runbook_template(
                name=body.name, steps=tuple(body.steps)
            )
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/operator-workspace/notebooks",
    tags=["operator-workspace"],
    status_code=status.HTTP_201_CREATED,
)
async def create_case_notebook(
    body: CaseNotebookRequest,
    service: Annotated[
        OperatorWorkspaceService, Depends(get_operator_workspace_service)
    ],
) -> dict[str, object]:
    try:
        return asdict(
            await service.create_notebook(
                title=body.title,
                created_by=body.created_by,
                incident_ids=tuple(body.incident_ids),
            )
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/operator-workspace/notebooks/{notebook_id}/entries",
    tags=["operator-workspace"],
    status_code=status.HTTP_201_CREATED,
)
async def add_case_notebook_entry(
    notebook_id: str,
    body: NotebookEntryRequest,
    service: Annotated[
        OperatorWorkspaceService, Depends(get_operator_workspace_service)
    ],
) -> dict[str, object]:
    try:
        return asdict(
            await service.add_notebook_entry(
                notebook_id=notebook_id,
                kind=NotebookEntryKind(body.kind),
                title=body.title,
                content=body.content,
                reference_id=body.reference_id,
                created_by=body.created_by,
            )
        )
    except LookupError as error:
        raise HTTPException(
            status_code=404, detail="Case notebook not found."
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/operator-workspace/notebooks/{notebook_id}/entries",
    tags=["operator-workspace"],
)
async def case_notebook_entries(
    notebook_id: str,
    service: Annotated[
        OperatorWorkspaceService, Depends(get_operator_workspace_service)
    ],
) -> list[dict[str, object]]:
    try:
        return [asdict(item) for item in await service.notebook_entries(notebook_id)]
    except LookupError as error:
        raise HTTPException(
            status_code=404, detail="Case notebook not found."
        ) from error


@router.get("/operator-workspace", tags=["operator-workspace"])
async def operator_workspace(
    service: Annotated[
        OperatorWorkspaceService, Depends(get_operator_workspace_service)
    ],
    incident_id: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    return await service.export_state(incident_id=incident_id)


@router.post("/mapping-workflows", tags=["interoperability"])
async def mapping_workflow(body: MappingWorkflowRequest) -> dict[str, object]:
    try:
        return asdict(
            build_mapping_workflow_package(incident_id=body.incident_id, aoi=body.aoi)
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/evidence-packages", tags=["interoperability"])
async def create_evidence_package(body: EvidencePackageCreateRequest) -> Response:
    try:
        content = EvidencePackageBuilder().build(
            incident_id=body.incident_id,
            incident_snapshot=body.incident_snapshot,
            source_links=tuple(body.source_links),
            normalized_data=body.normalized_data,
            findings=tuple(body.findings),
            imagery_manifests=tuple(body.imagery_manifests),
            software_version=body.software_version,
            policy_versions=tuple(body.policy_versions),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="evidence-{body.incident_id}.zip"'
            )
        },
    )


@router.post("/evidence-packages/verify", tags=["interoperability"])
async def verify_evidence_package(
    body: EvidencePackageVerifyRequest,
) -> dict[str, object]:
    try:
        content = base64.b64decode(body.content_base64, validate=True)
        return asdict(EvidencePackageVerifier().verify(content))
    except (binascii.Error, EvidencePackageVerificationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


__all__ = ["router"]
