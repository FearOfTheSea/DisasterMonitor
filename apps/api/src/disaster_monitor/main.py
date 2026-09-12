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
    *,
    overrides: AppDependencyOverrides | None = None,
    dependencies: AppDependencies | None = None,
) -> FastAPI:
    """Bootstrap FastAPI from typed overrides or a prebuilt dependency graph."""
    app_settings = settings or Settings()
    if dependencies is not None and overrides is not None:
        raise ValueError("Prebuilt dependencies cannot be combined with overrides.")

    metrics = (
        dependencies.agent_diagnostics
        if dependencies is not None
        and isinstance(dependencies.agent_diagnostics, OperationalMetrics)
        else overrides.agent_diagnostics
        if overrides is not None
        and isinstance(overrides.agent_diagnostics, OperationalMetrics)
        else OperationalMetrics()
    )
    app_dependencies = dependencies
    if app_dependencies is None:
        configured_overrides = overrides or AppDependencyOverrides()
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
        allow_methods=["DELETE", "GET", "POST", "PUT"],
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
