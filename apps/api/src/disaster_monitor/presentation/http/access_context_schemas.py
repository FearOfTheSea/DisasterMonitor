"""Transport schemas for bounded local route context."""

from pydantic import BaseModel

from disaster_monitor.domain.exposure import RouteProfile


class RouteCoordinateRequest(BaseModel):
    longitude: float
    latitude: float


class RouteAccessRequest(BaseModel):
    origin: RouteCoordinateRequest
    destination: RouteCoordinateRequest
    profile: RouteProfile = RouteProfile.DRIVING
