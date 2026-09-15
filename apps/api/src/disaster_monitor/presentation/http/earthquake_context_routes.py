"""HTTP projection for selected-event USGS analytical context."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder

from disaster_monitor.application.earthquake_context import EarthquakeContextService
from disaster_monitor.application.ports.earthquake_context import (
    EarthquakeContextProviderError,
)

router = APIRouter(prefix="/earthquakes")


def get_earthquake_context_service(request: Request) -> EarthquakeContextService:
    return cast(
        EarthquakeContextService, request.app.state.dependencies.earthquake_context
    )


@router.get("/{event_id}/context", response_model=None)
async def earthquake_context(
    event_id: str,
    service: Annotated[
        EarthquakeContextService, Depends(get_earthquake_context_service)
    ],
) -> dict[str, Any]:
    try:
        context = await service.execute(event_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except EarthquakeContextProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return cast(dict[str, Any], jsonable_encoder(context))
