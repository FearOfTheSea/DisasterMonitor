"""HTTP request and response schemas."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class MapViewRequest(BaseModel):
    """Optional current browser map view."""

    model_config = ConfigDict(extra="forbid")

    center_latitude: Annotated[float, Field(ge=-90, le=90)]
    center_longitude: Annotated[float, Field(ge=-180, le=180)]
    zoom: Annotated[float, Field(ge=0, le=24)]


class AssistantRequest(BaseModel):
    """Assistant request accepted by the public API."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: Annotated[str, Field(min_length=1, max_length=2_000)]
    conversation_id: Annotated[str | None, Field(max_length=100)] = None
    map_view: MapViewRequest | None = None


class AssistantResponse(BaseModel):
    """Stable assistant response returned to the frontend."""

    message: str
    conversation_id: str
    model: str
    response_type: str = "assistant"
    selected_event: "SelectedEventResponse | None" = None
    retrieval_time: datetime | None = None
    sources: list["SourceResponse"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sections: list["ReportSectionResponse"] = Field(default_factory=list)
    partial: bool = False


class SourceResponse(BaseModel):
    """Source metadata exposed to the browser."""

    publisher: str
    title: str
    canonical_url: str
    published_at: datetime | None = None
    updated_at: datetime | None = None
    retrieved_at: datetime


class SelectedEventResponse(BaseModel):
    """The specific event covered by a current-disaster report."""

    event_id: str
    hazard: str
    location: str
    event_time: datetime
    magnitude: float | None = None
    intensity: str | None = None
    depth_km: float | None = None
    source: SourceResponse
    provider_ids: list[str] = Field(default_factory=list)


class ReportSectionResponse(BaseModel):
    """One readable report section."""

    title: str
    content: str


class HealthResponse(BaseModel):
    """Liveness response."""

    status: str
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Local-model readiness response."""

    status: str
    ollama_available: bool
    model_available: bool
    model: str
