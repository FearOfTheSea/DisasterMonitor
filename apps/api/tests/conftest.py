"""Shared deterministic model doubles for backend tests."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from disaster_monitor.application.dto import (
    ModelReadiness,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)


@pytest.fixture(autouse=True)
def isolated_country_catalog_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep ignored live catalog data from changing deterministic test baselines."""
    monkeypatch.setenv("COUNTRY_CATALOG_ROOT", str(tmp_path / "country-catalog"))
    monkeypatch.setenv("EVENT_MEDIA_ENABLED", "false")


@dataclass
class FakeLanguageModel:
    response_text: str = "A deterministic local answer."
    model: str = "fake-qwen"
    tool_calls: tuple[ModelToolCall, ...] = ()
    requests: list[ModelRequest] = field(default_factory=list)
    readiness: ModelReadiness = field(
        default_factory=lambda: ModelReadiness(True, True, "fake-qwen")
    )
    error: Exception | None = None

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return ModelResponse(
            text=self.response_text,
            model=self.model,
            tool_calls=self.tool_calls,
        )

    async def check_readiness(self) -> ModelReadiness:
        return self.readiness
