"""FastAPI bootstrap and local server entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from time import perf_counter

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.conversation_deletion import (
    ConversationDeletionStore,
)
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.ports.event_media import (
    EventMediaDiscovery,
    MediaAssetStore,
)
from disaster_monitor.application.ports.geography import CountryCatalogUpdateAutomation
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.memory_store import MemoryStore
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.specialist_model import SpecialistModel
from disaster_monitor.application.ports.visual_analysis import VisualAnalyzer
from disaster_monitor.application.satellite_imagery import SatelliteImageryService
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.infrastructure.app_dependencies import AppDependencies
from disaster_monitor.infrastructure.composition import (
    AppDependencyOverrides,
    build_app_dependencies,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.presentation.http.api import create_http_app
from disaster_monitor.presentation.http.metrics import OperationalMetrics
from disaster_monitor.presentation.http.routes import get_operational_metrics


def create_app(
    settings: Settings | None = None,
    model: LanguageModel | None = None,
    current_disaster_report: CurrentDisasterReportService | None = None,
    disaster_query_parser: DisasterQueryParser | None = None,
    agent_model: AgentModel | None = None,
    visual_analyzer: VisualAnalyzer | None = None,
    operational_repository: OperationalRepository | None = None,
    country_catalog_automation: CountryCatalogUpdateAutomation | None = None,
    worldwide_disaster_report: WorldwideDisasterReportService | None = None,
    event_media: EventMediaDiscovery | None = None,
    media_asset_store: MediaAssetStore | None = None,
    active_incidents_service: ActiveIncidentsService | None = None,
    conversation_repository: ConversationStore | None = None,
    satellite_imagery_service: SatelliteImageryService | None = None,
    specialist_model: SpecialistModel | None = None,
    memory_repository: MemoryStore | None = None,
    conversation_deletion_store: ConversationDeletionStore | None = None,
    *,
    overrides: AppDependencyOverrides | None = None,
    dependencies: AppDependencies | None = None,
) -> FastAPI:
    """Bootstrap FastAPI from typed overrides or a prebuilt dependency graph."""
    app_settings = settings or Settings()
    legacy_overrides = AppDependencyOverrides(
        model=model,
        current_disaster_report=current_disaster_report,
        disaster_query_parser=disaster_query_parser,
        agent_model=agent_model,
        visual_analyzer=visual_analyzer,
        operational_repository=operational_repository,
        country_catalog_automation=country_catalog_automation,
        worldwide_disaster_report=worldwide_disaster_report,
        event_media=event_media,
        media_asset_store=media_asset_store,
        active_incidents_service=active_incidents_service,
        conversation_repository=conversation_repository,
        satellite_imagery_service=satellite_imagery_service,
        specialist_model=specialist_model,
        memory_repository=memory_repository,
        conversation_deletion_store=conversation_deletion_store,
    )
    has_legacy_overrides = any(
        value is not None
        for value in (
            model,
            current_disaster_report,
            disaster_query_parser,
            agent_model,
            visual_analyzer,
            operational_repository,
            country_catalog_automation,
            worldwide_disaster_report,
            event_media,
            media_asset_store,
            active_incidents_service,
            conversation_repository,
            satellite_imagery_service,
            specialist_model,
            memory_repository,
            conversation_deletion_store,
        )
    )
    if overrides is not None and has_legacy_overrides:
        raise ValueError("Use either typed overrides or legacy keyword overrides.")
    if dependencies is not None and (overrides is not None or has_legacy_overrides):
        raise ValueError("Prebuilt dependencies cannot be combined with overrides.")

    metrics = (
        dependencies.agent_diagnostics
        if dependencies is not None
        and isinstance(dependencies.agent_diagnostics, OperationalMetrics)
        else OperationalMetrics()
    )
    app_dependencies = dependencies
    if app_dependencies is None:
        configured_overrides = overrides or legacy_overrides
        if configured_overrides.agent_diagnostics is None:
            configured_overrides = replace(
                configured_overrides,
                agent_diagnostics=metrics,
            )
        app_dependencies = build_app_dependencies(
            app_settings,
            overrides=configured_overrides,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await app_dependencies.lifecycle.startup()
        try:
            yield
        finally:
            await app_dependencies.lifecycle.shutdown()

    app = create_http_app(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def record_http_metrics(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        started = perf_counter()
        metrics.in_progress.inc()
        try:
            response = await call_next(request)
        except Exception:
            metrics.requests.labels(request.method, path, "500").inc()
            raise
        else:
            metrics.requests.labels(
                request.method, path, str(response.status_code)
            ).inc()
            return response
        finally:
            metrics.request_duration.labels(request.method, path).observe(
                perf_counter() - started
            )
            metrics.in_progress.dec()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["DELETE", "GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.dependencies = app_dependencies
    app.dependency_overrides[get_operational_metrics] = lambda: metrics
    return app


app = create_app()


def run() -> None:
    """Run the development server."""
    uvicorn.run("disaster_monitor.main:app", host="127.0.0.1", port=8001)


if __name__ == "__main__":
    run()
