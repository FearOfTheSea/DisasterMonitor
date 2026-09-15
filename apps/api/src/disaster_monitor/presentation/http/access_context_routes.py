"""HTTP boundary for non-operational local route visualization context."""

from dataclasses import asdict
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from disaster_monitor.application.exposure.access_context import (
    RouteAccessContextService,
)
from disaster_monitor.domain.imagery.regions import Coordinate
from disaster_monitor.presentation.http.access_context_schemas import (
    RouteAccessRequest,
)

router = APIRouter()


def get_route_access_service(request: Request) -> RouteAccessContextService:
    service = request.app.state.dependencies.route_access
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Self-hosted route context is not configured.",
        )
    return cast(RouteAccessContextService, service)


@router.post("/access-context/routes", tags=["access-context"])
async def route_access_context(
    body: RouteAccessRequest,
    service: Annotated[RouteAccessContextService, Depends(get_route_access_service)],
) -> dict[str, object]:
    try:
        result = await service.estimate(
            Coordinate(body.origin.latitude, body.origin.longitude),
            Coordinate(body.destination.latitude, body.destination.longitude),
            body.profile,
        )
        return asdict(result)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


__all__ = ["get_route_access_service", "router"]
