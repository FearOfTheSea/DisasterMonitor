"""Shared deterministic model doubles for backend tests."""

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    """Require PostgreSQL in its dedicated gate and skip it elsewhere."""
    dsn = os.environ.get("OPERATIONAL_DATABASE_URL", "").strip()
    if dsn:
        return dsn
    if os.environ.get("REQUIRE_POSTGRES_TESTS", "").strip().casefold() in {
        "1",
        "true",
        "yes",
    }:
        pytest.fail(
            "REQUIRE_POSTGRES_TESTS is enabled but OPERATIONAL_DATABASE_URL is absent."
        )
    pytest.skip("OPERATIONAL_DATABASE_URL is not configured")


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
