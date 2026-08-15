"""FastAPI application factory and local server entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import perf_counter

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from disaster_monitor.application.agent.multimodal_tools import (
    MultimodalToolDependencies,
    build_multimodal_agent_tools,
)
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.visual_analysis import VisualAnalyzer
from disaster_monitor.application.services.common_operational_picture import (
    CommonOperationalPictureBuilder,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.multimodal_asset_admission import (
    MultimodalAssetAdmissionService,
)
from disaster_monitor.application.services.multimodal_association import (
    MultimodalEventAssociator,
)
from disaster_monitor.application.services.visual_analysis import VisualAnalysisService
from disaster_monitor.application.use_cases.answer_map_question import AnswerMapQuestion
from disaster_monitor.application.use_cases.run_disaster_agent import RunDisasterAgent
from disaster_monitor.infrastructure.composition import (
    build_agent_model,
    build_country_catalog,
    build_current_disaster_report,
    build_disaster_query_parser,
    build_language_model,
    build_operational_services,
    build_source_catalog,
    build_visual_analyzer,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)
from disaster_monitor.presentation.http.error_handlers import register_error_handlers
from disaster_monitor.presentation.http.metrics import OperationalMetrics
from disaster_monitor.presentation.http.routes import router


def create_app(
    settings: Settings | None = None,
    model: LanguageModel | None = None,
    current_disaster_report: CurrentDisasterReportService | None = None,
    disaster_query_parser: DisasterQueryParser | None = None,
    agent_model: AgentModel | None = None,
    visual_analyzer: VisualAnalyzer | None = None,
    operational_repository: OperationalRepository | None = None,
) -> FastAPI:
    """Build an application with explicit, testable dependencies."""
    app_settings = settings or Settings()
    language_model = model or build_language_model(app_settings)
    country_catalog = build_country_catalog()
    operational = build_operational_services(app_settings, operational_repository)
    disaster_report = current_disaster_report or build_current_disaster_report(
        app_settings,
        country_catalog,
        snapshot_recorder=operational.snapshots.persist,
        operational_evidence=operational.evidence,
    )
    query_parser = disaster_query_parser or build_disaster_query_parser(country_catalog)
    source_catalog = build_source_catalog(app_settings)
    configured_agent_model = (
        agent_model
        if agent_model is not None
        else (build_agent_model(app_settings) if model is None else None)
    )
    configured_visual_analyzer = visual_analyzer or build_visual_analyzer(app_settings)

    def clock() -> datetime:
        return datetime.now(UTC)

    asset_admission = MultimodalAssetAdmissionService(clock=clock)
    multimodal_tools = build_multimodal_agent_tools(
        MultimodalToolDependencies(
            associator=MultimodalEventAssociator(),
            visual_analysis=VisualAnalysisService(
                configured_visual_analyzer,
                clock=clock,
            ),
            cop_builder=CommonOperationalPictureBuilder(),
            clock=clock,
        )
    )
    agent_runtime = DisasterAgentRuntime(
        country_catalog=country_catalog,
        query_parser=query_parser,
        tool_registry=disaster_report.build_agent_tools(
            source_catalog, multimodal_tools
        ),
        agent_model=configured_agent_model,
    )
    disaster_agent = RunDisasterAgent(
        agent_runtime,
        language_model,
        asset_admission,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app_settings.operational_auto_migrate and isinstance(
            operational.repository, PostgresOperationalRepository
        ):
            await operational.repository.migrate()
        yield
        close = getattr(app.state.language_model, "aclose", None)
        if close is not None:
            await close()
        close_disaster = getattr(app.state.current_disaster_report, "aclose", None)
        if close_disaster is not None:
            await close_disaster()
        close_agent = getattr(app.state.agent_model, "aclose", None)
        if close_agent is not None:
            await close_agent()
        close_visual = getattr(app.state.visual_analyzer, "aclose", None)
        if close_visual is not None:
            await close_visual()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    metrics = OperationalMetrics()

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
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.language_model = language_model
    app.state.current_disaster_report = disaster_report
    app.state.agent_model = configured_agent_model
    app.state.visual_analyzer = configured_visual_analyzer
    app.state.answer_map_question = AnswerMapQuestion(
        language_model,
        disaster_report,
        query_parser,
        disaster_agent=disaster_agent,
    )
    app.state.operational_repository = operational.repository
    app.state.settings = app_settings
    app.state.operational_metrics = metrics
    app.include_router(router, prefix="/api/v1")
    register_error_handlers(app)
    return app


app = create_app()


def run() -> None:
    """Run the development server."""
    uvicorn.run("disaster_monitor.main:app", host="127.0.0.1", port=8001)


if __name__ == "__main__":
    run()
