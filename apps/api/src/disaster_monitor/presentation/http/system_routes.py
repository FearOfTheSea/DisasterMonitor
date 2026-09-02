"""FastAPI routes for the MVP."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response

from disaster_monitor.application.dto import ModelReadiness
from disaster_monitor.application.ports.geography import (
    CountryCatalogUpdateAutomation,
    CountryCatalogUpdateTrigger,
)
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.services.provider_freshness import (
    ProviderFreshnessService,
)
from disaster_monitor.presentation.http.metrics import OperationalMetrics
from disaster_monitor.presentation.http.response_serialization import (
    _country_catalog_response,
)
from disaster_monitor.presentation.http.schemas import (
    CountryCatalogUpdateResponse,
    HealthResponse,
    ProviderFreshnessResponse,
    ReadinessResponse,
)

router = APIRouter()


def get_language_model(request: Request) -> LanguageModel:
    """Retrieve the provider-neutral model port built by the composition root."""
    return cast(LanguageModel, request.app.state.dependencies.language_model)


def get_operational_repository(request: Request) -> OperationalRepository:
    """Retrieve the operational store built by the composition root."""
    return cast(
        OperationalRepository, request.app.state.dependencies.operational_repository
    )


def get_operational_metrics() -> OperationalMetrics:
    """Require the HTTP bootstrap to provide its presentation metrics adapter."""
    raise RuntimeError("Operational metrics were not configured.")


def get_provider_freshness(request: Request) -> ProviderFreshnessService:
    return cast(
        ProviderFreshnessService, request.app.state.dependencies.provider_freshness
    )


def get_country_catalog_automation(request: Request) -> CountryCatalogUpdateAutomation:
    """Retrieve autonomous catalog updates from the composition root."""
    return cast(
        CountryCatalogUpdateAutomation,
        request.app.state.dependencies.country_catalog_automation,
    )


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


@router.get(
    "/operations/providers",
    response_model=list[ProviderFreshnessResponse],
    tags=["operations"],
)
async def provider_freshness(
    service: Annotated[ProviderFreshnessService, Depends(get_provider_freshness)],
) -> list[ProviderFreshnessResponse]:
    """Expose upstream freshness and failures without hiding unavailable sources."""
    values = await service.list()
    return [
        ProviderFreshnessResponse(
            source_id=item.source_id,
            state=item.state.value,
            last_attempt_at=item.last_attempt_at,
            last_success_at=item.last_success_at,
            effective_at=item.effective_at,
            age_seconds=item.age_seconds,
            expected_freshness_seconds=item.expected_freshness_seconds,
            consecutive_failures=item.consecutive_failures,
            latest_error_code=item.latest_error_code,
        )
        for item in values
    ]


@router.get(
    "/operations/country-catalog",
    response_model=CountryCatalogUpdateResponse,
    tags=["operations"],
)
async def country_catalog_status(
    automation: Annotated[
        CountryCatalogUpdateAutomation, Depends(get_country_catalog_automation)
    ],
) -> CountryCatalogUpdateResponse:
    """Expose active provenance and the next autonomous monthly attempt."""
    return _country_catalog_response(automation.status())


@router.post(
    "/operations/country-catalog/update",
    response_model=CountryCatalogUpdateResponse,
    tags=["operations"],
)
async def update_country_catalog(
    automation: Annotated[
        CountryCatalogUpdateAutomation, Depends(get_country_catalog_automation)
    ],
) -> CountryCatalogUpdateResponse:
    """Run the same fail-closed path used by monthly automation immediately."""
    result = await automation.request_update(CountryCatalogUpdateTrigger.MANUAL)
    return _country_catalog_response(result)


@router.get("/metrics", tags=["operations"])
async def metrics(
    repository: Annotated[OperationalRepository, Depends(get_operational_repository)],
    operational_metrics: Annotated[
        OperationalMetrics, Depends(get_operational_metrics)
    ],
) -> Response:
    """Expose API and durable queue metrics for an owner-selected scraper."""
    operational_metrics.update_jobs(await repository.job_status_counts())
    content, content_type = operational_metrics.render()
    return Response(content=content, media_type=content_type)
