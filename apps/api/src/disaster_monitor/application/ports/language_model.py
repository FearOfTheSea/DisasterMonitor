"""Port for the local language-model runtime."""

from typing import Protocol

from disaster_monitor.application.dto import ModelReadiness, ModelRequest, ModelResponse


class LanguageModel(Protocol):
    """Generate text and report local runtime readiness."""

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate a response for a provider-neutral request."""
        ...

    async def check_readiness(self) -> ModelReadiness:
        """Report service and configured-model availability without inference."""
        ...
