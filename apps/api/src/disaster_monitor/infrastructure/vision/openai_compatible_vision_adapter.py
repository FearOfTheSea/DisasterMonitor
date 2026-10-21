"""OpenAI-compatible image analysis adapter sharing the strict local result parser."""

import base64
import json
from typing import Any

import httpx

from disaster_monitor.application.multimodal import (
    VisualAnalysisRequest,
    VisualModelPrediction,
    VisualModelReadiness,
)
from disaster_monitor.application.prompts.visual_analysis import (
    VISUAL_ANALYSIS_SYSTEM_PROMPT,
    visual_analysis_prompt,
)
from disaster_monitor.domain.errors import ModelResponseError, ModelRuntimeError
from disaster_monitor.infrastructure.vision.ollama_vision_adapter import (
    OllamaVisionAdapter,
)

_SEED = 7


class OpenAICompatibleVisionAdapter(OllamaVisionAdapter):
    """Send image analysis requests to a compatible multimodal chat endpoint."""

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 180.0,
        max_tokens: int = 384,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=timeout_seconds, headers=headers)
        super().__init__(
            model_name,
            base_url,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            client=client,
            adapter_version="openai-compatible-vision-v1",
        )
        self._owns_client = owns_client

    async def analyze(self, request: VisualAnalysisRequest) -> VisualModelPrediction:
        image = base64.b64encode(request.asset.content).decode("ascii")
        image_url = f"data:{request.asset.media_type};base64,{image}"
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                json={
                    "model": self._model_name,
                    "messages": [
                        {"role": "system", "content": VISUAL_ANALYSIS_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": visual_analysis_prompt(request.question),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image_url},
                                },
                            ],
                        },
                    ],
                    "max_tokens": self._max_tokens,
                    "temperature": 0,
                    "seed": _SEED,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ModelRuntimeError(
                "The configured multimodal model provider is unavailable."
            ) from error
        payload = self._payload(response)
        choices = payload.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else None
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError(
                "The model provider returned no visual JSON content."
            )
        try:
            item: Any = json.loads(content)
        except json.JSONDecodeError as error:
            raise ModelResponseError(
                "The model provider returned invalid visual JSON."
            ) from error
        return self._prediction(item)

    async def check_readiness(self) -> VisualModelReadiness:
        try:
            response = await self._client.get(f"{self._base_url}/models")
            response.raise_for_status()
            body = self._payload(response)
        except (httpx.HTTPError, ModelResponseError):
            return self._readiness(False, False)
        items = body.get("data")
        available = isinstance(items, list) and any(
            isinstance(item, dict) and item.get("id") == self._model_name
            for item in items
        )
        return self._readiness(True, available)

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as error:
            raise ModelResponseError(
                "The model provider returned invalid JSON."
            ) from error
        if not isinstance(body, dict):
            raise ModelResponseError("The model provider returned an invalid payload.")
        return body
