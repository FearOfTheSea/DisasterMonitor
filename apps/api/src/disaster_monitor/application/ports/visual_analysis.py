"""Port for bounded local multimodal inference."""

from typing import Protocol

from disaster_monitor.application.multimodal import (
    VisualAnalysisRequest,
    VisualModelPrediction,
    VisualModelReadiness,
)


class VisualAnalyzer(Protocol):
    """Analyze admitted bytes without granting the result source authority."""

    async def analyze(
        self, request: VisualAnalysisRequest
    ) -> VisualModelPrediction: ...

    async def check_readiness(self) -> VisualModelReadiness: ...
