"""Deterministic FastAPI server used by the Playwright system test."""

import sys
from pathlib import Path

import uvicorn

api_src = Path(__file__).resolve().parents[1] / "apps" / "api" / "src"
sys.path.insert(0, str(api_src))

from disaster_monitor.application.dto import ModelReadiness, ModelRequest, ModelResponse  # noqa: E402
from disaster_monitor.main import create_app  # noqa: E402


class FakeSystemModel:
    async def generate(self, _request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text="Deterministic system-test response.",
            model="fake-qwen",
        )

    async def check_readiness(self) -> ModelReadiness:
        return ModelReadiness(True, True, "fake-qwen")


if __name__ == "__main__":
    uvicorn.run(
        create_app(model=FakeSystemModel()),
        host="127.0.0.1",
        port=8787,
        log_level="warning",
    )
