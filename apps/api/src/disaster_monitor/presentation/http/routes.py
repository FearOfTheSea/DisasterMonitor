"""FastAPI routes for the MVP."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status

from disaster_monitor.application.dto import ModelReadiness
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.use_cases.answer_map_question import AnswerMapQuestion
from disaster_monitor.domain.models import MapView
from disaster_monitor.presentation.http.schemas import (
    AssistantRequest,
    AssistantResponse,
    HealthResponse,
    InvestigationResponse,
    ReadinessResponse,
    ReportSectionResponse,
    SelectedEventResponse,
    SourceResponse,
)

router = APIRouter()


def get_answer_use_case(request: Request) -> AnswerMapQuestion:
    """Retrieve the use case built by the composition root."""
    return cast(AnswerMapQuestion, request.app.state.answer_map_question)


def get_language_model(request: Request) -> LanguageModel:
    """Retrieve the provider-neutral model port built by the composition root."""
    return cast(LanguageModel, request.app.state.language_model)


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Return liveness without contacting Ollama."""
    return HealthResponse(status="ok", service="disaster-monitor-api", version="0.1.0")


@router.get("/ready", response_model=ReadinessResponse, tags=["system"])
async def readiness(
    language_model: Annotated[LanguageModel, Depends(get_language_model)],
) -> ReadinessResponse:
    """Check local Ollama and the configured Qwen model without inference."""
    result: ModelReadiness = await language_model.check_readiness()
    return ReadinessResponse(
        status="ready"
        if result.ollama_available and result.model_available
        else "unavailable",
        ollama_available=result.ollama_available,
        model_available=result.model_available,
        model=result.model,
    )


@router.post(
    "/assistant",
    response_model=AssistantResponse,
    response_model_exclude_unset=True,
    status_code=status.HTTP_200_OK,
    tags=["assistant"],
)
async def assistant(
    request: AssistantRequest,
    use_case: Annotated[AnswerMapQuestion, Depends(get_answer_use_case)],
) -> AssistantResponse:
    """Answer a map-related question through the application use case."""
    result = await use_case.execute(
        question=request.question,
        conversation_id=request.conversation_id,
        map_view=(
            None
            if request.map_view is None
            else MapView(
                center_latitude=request.map_view.center_latitude,
                center_longitude=request.map_view.center_longitude,
                zoom=request.map_view.zoom,
            )
        ),
    )
    investigation = (
        None
        if result.investigation is None
        else InvestigationResponse(
            status=result.investigation.status,
            task_summary=result.investigation.task_summary,
            hazard=result.investigation.hazard,
            country=result.investigation.country,
            information_needs=list(result.investigation.information_needs),
            output_modalities=list(result.investigation.output_modalities),
            actions=list(result.investigation.actions),
            source_ids=list(result.investigation.source_ids),
            evidence_count=result.investigation.evidence_count,
            capability_gaps=list(result.investigation.capability_gaps),
            termination_reason=result.investigation.termination_reason,
        )
    )
    if result.response_type == "assistant":
        return AssistantResponse(
            message=result.message,
            conversation_id=result.conversation_id,
            model=result.model,
        )
    selected_event = result.selected_event
    return AssistantResponse(
        message=result.message,
        conversation_id=result.conversation_id,
        model=result.model,
        response_type=result.response_type,
        selected_event=(
            None
            if selected_event is None
            else SelectedEventResponse(
                event_id=selected_event.event_id,
                hazard=selected_event.hazard,
                location=selected_event.location,
                event_time=selected_event.event_time,
                magnitude=selected_event.magnitude,
                intensity=selected_event.intensity,
                depth_km=selected_event.depth_km,
                provider_ids=list(selected_event.provider_ids),
                source=SourceResponse(
                    publisher=selected_event.source.publisher,
                    title=selected_event.source.title,
                    canonical_url=selected_event.source.canonical_url,
                    published_at=selected_event.source.published_at,
                    updated_at=selected_event.source.updated_at,
                    retrieved_at=selected_event.source.retrieved_at,
                ),
            )
        ),
        retrieval_time=result.retrieval_time,
        sources=[
            SourceResponse(
                publisher=source.publisher,
                title=source.title,
                canonical_url=source.canonical_url,
                published_at=source.published_at,
                updated_at=source.updated_at,
                retrieved_at=source.retrieved_at,
            )
            for source in result.sources
        ],
        warnings=list(result.warnings),
        sections=[
            ReportSectionResponse(title=section.title, content=section.content)
            for section in result.sections
        ],
        partial=result.partial,
        investigation=investigation,
    )
