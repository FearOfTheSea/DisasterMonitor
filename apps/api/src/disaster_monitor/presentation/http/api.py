"""FastAPI shell shared by production bootstrap and schema generation."""

from fastapi import FastAPI
from starlette.types import Lifespan

from disaster_monitor.presentation.http.error_handlers import register_error_handlers
from disaster_monitor.presentation.http.routes import router


def create_http_app(
    *,
    title: str,
    version: str = "0.1.0",
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """Register the production routes and schemas without constructing adapters."""
    app = FastAPI(title=title, version=version, lifespan=lifespan)
    app.include_router(router, prefix="/api/v1")
    register_error_handlers(app)
    return app


def create_schema_app() -> FastAPI:
    """Create the side-effect-free HTTP shell used for OpenAPI generation."""
    return create_http_app(title="Disaster Monitor API")
