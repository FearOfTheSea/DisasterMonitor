"""FastAPI application factory and local server entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from disaster_monitor.application.ports.disaster_information import (
    DisasterInformationProvider,
)
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.use_cases.answer_map_question import AnswerMapQuestion
from disaster_monitor.infrastructure.composition import (
    build_disaster_information_provider,
    build_language_model,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.presentation.http.error_handlers import register_error_handlers
from disaster_monitor.presentation.http.routes import router


def create_app(
    settings: Settings | None = None,
    model: LanguageModel | None = None,
    disaster_information_provider: DisasterInformationProvider | None = None,
) -> FastAPI:
    """Build an application with explicit, testable dependencies."""
    app_settings = settings or Settings()
    language_model = model or build_language_model(app_settings)
    information_provider = (
        disaster_information_provider
        or build_disaster_information_provider(app_settings)
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        for dependency_name in (
            "language_model",
            "disaster_information_provider",
        ):
            dependency = getattr(app.state, dependency_name)
            close = getattr(dependency, "aclose", None)
            if close is not None:
                await close()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.language_model = language_model
    app.state.disaster_information_provider = information_provider
    app.state.answer_map_question = AnswerMapQuestion(
        language_model,
        information_provider,
    )
    app.include_router(router, prefix="/api/v1")
    register_error_handlers(app)
    return app


app = create_app()


def run() -> None:
    """Run the development server."""
    uvicorn.run("disaster_monitor.main:app", host="127.0.0.1", port=8001)


if __name__ == "__main__":
    run()
