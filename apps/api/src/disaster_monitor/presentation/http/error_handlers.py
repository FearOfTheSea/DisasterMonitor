"""Stable HTTP translations for application errors."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from disaster_monitor.domain.errors import (
    InvalidQuestionError,
    ModelResponseError,
    ModelRuntimeError,
    MultimodalInputError,
)


def register_error_handlers(app: FastAPI) -> None:
    """Keep domain and provider details out of HTTP responses."""

    @app.exception_handler(InvalidQuestionError)
    async def handle_invalid_question(
        _request: Request, error: InvalidQuestionError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(ModelRuntimeError)
    async def handle_model_runtime_error(
        _request: Request, _error: ModelRuntimeError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": (
                    "The local model is unavailable. Start Ollama and pull the "
                    "configured Qwen model, then try again."
                )
            },
        )

    @app.exception_handler(MultimodalInputError)
    async def handle_multimodal_input_error(
        _request: Request, error: MultimodalInputError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(ModelResponseError)
    async def handle_model_response_error(
        _request: Request, _error: ModelResponseError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": "The local model returned an invalid response."},
        )
