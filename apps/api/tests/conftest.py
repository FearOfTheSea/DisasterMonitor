"""Shared deterministic doubles for backend tests."""

from dataclasses import dataclass, field

from disaster_monitor.application.dto import (
    DisasterInformationResult,
    ModelReadiness,
    ModelRequest,
    ModelResponse,
)


@dataclass
class FakeLanguageModel:
    response_text: str = "A deterministic local answer."
    model: str = "fake-qwen"
    requests: list[ModelRequest] = field(default_factory=list)
    readiness: ModelReadiness = field(
        default_factory=lambda: ModelReadiness(True, True, "fake-qwen")
    )
    error: Exception | None = None

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return ModelResponse(text=self.response_text, model=self.model)

    async def check_readiness(self) -> ModelReadiness:
        return self.readiness


@dataclass
class FakeDisasterInformationProvider:
    result: DisasterInformationResult | None = None
    error: Exception | None = None
    queries: list[str] = field(default_factory=list)

    async def search(self, query: str) -> DisasterInformationResult:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("A fake disaster-information result is required.")
        return self.result
