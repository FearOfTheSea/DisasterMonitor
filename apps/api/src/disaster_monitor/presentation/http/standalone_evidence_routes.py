"""Typed section retrieval independent of assistant messages."""

from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from disaster_monitor.application.evidence.standalone import StandaloneEvidenceService
from disaster_monitor.application.evidence.standalone_models import (
    StandaloneEvidenceResult,
)


class SectionEvidenceResponse(BaseModel):
    evidence: StandaloneEvidenceResult
    contract_version: str = "1"


router = APIRouter()


def _service(request: Request) -> StandaloneEvidenceService:
    service = request.app.state.dependencies.standalone_evidence
    if service is None:
        raise HTTPException(
            status_code=503, detail="Standalone evidence is not configured."
        )
    return cast(StandaloneEvidenceService, service)


@router.get(
    "/incidents/{identifier}/evidence/{section}",
    response_model=SectionEvidenceResponse,
    tags=["incidents"],
)
async def section_evidence(
    identifier: str,
    section: str,
    request: Request,
    cursor: Annotated[str | None, Query(min_length=1, max_length=8192)] = None,
) -> SectionEvidenceResponse:
    service = _service(request)
    try:
        return SectionEvidenceResponse(
            evidence=await service.execute(identifier, section, cursor=cursor)
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=409 if "ambiguous" in str(error).lower() else 400,
            detail=str(error),
        ) from error


class ExposureInspectionRequest(BaseModel):
    bounds: tuple[float, float, float, float]


@router.post(
    "/incidents/{identifier}/evidence/exposure/inspection",
    response_model=SectionEvidenceResponse,
    tags=["incidents"],
)
async def inspection_exposure(
    identifier: str, body: ExposureInspectionRequest, request: Request
) -> SectionEvidenceResponse:
    service = _service(request)
    try:
        return SectionEvidenceResponse(
            evidence=await service.execute_inspection(identifier, body.bounds)
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
