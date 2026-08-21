"""Ollama adapter for a locally running Qwen model."""

from typing import Any

import httpx

from disaster_monitor.application.dto import (
    ModelReadiness,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from disaster_monitor.domain.errors import ModelResponseError, ModelRuntimeError


class OllamaQwenAdapter:
    """Translate the application model port to Ollama's local HTTP API."""

    def __init__(
        self,
        model_name: str,
        base_url: str,
        timeout_seconds: float = 60.0,
        max_tokens: int = 512,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate one non-streaming answer from Ollama's chat endpoint."""
        request_payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "stream": False,
            "think": False,
            "options": {
                "num_predict": request.max_tokens or self._max_tokens,
                "temperature": 0.2,
            },
        }
        if request.tools:
            request_payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat",
                json=request_payload,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ModelRuntimeError(
                "The local Ollama service is unavailable or rejected the request."
            ) from error

        payload = self._payload(response)
        message = payload.get("message")
        generated_text = message.get("content") if isinstance(message, dict) else None
        tool_calls = self._tool_calls(
            message.get("tool_calls") if isinstance(message, dict) else None
        )
        if not isinstance(generated_text, str):
            generated_text = ""
        if not generated_text.strip() and not tool_calls:
            raise ModelResponseError("Ollama returned an empty response.")
        return ModelResponse(
            text=generated_text.strip(),
            model=self._model_name,
            tool_calls=tool_calls,
        )

    async def check_readiness(self) -> ModelReadiness:
        """Check the Ollama service and whether the configured model is installed."""
        try:
            response = await self._client.get(f"{self._base_url}/api/tags")
            response.raise_for_status()
            payload = self._payload(response)
        except (httpx.HTTPError, ModelResponseError):
            return ModelReadiness(
                ollama_available=False,
                model_available=False,
                model=self._model_name,
            )

        models = payload.get("models")
        model_available = isinstance(models, list) and any(
            isinstance(model, dict) and model.get("name") == self._model_name
            for model in models
        )
        return ModelReadiness(
            ollama_available=True,
            model_available=model_available,
            model=self._model_name,
        )

    async def aclose(self) -> None:
        """Close the adapter-owned HTTP client at application shutdown."""
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise ModelResponseError("Ollama returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise ModelResponseError("Ollama returned an invalid response payload.")
        return payload

    @staticmethod
    def _tool_calls(value: object) -> tuple[ModelToolCall, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise ModelResponseError("Ollama returned invalid tool calls.")
        calls: list[ModelToolCall] = []
        for item in value:
            if not isinstance(item, dict):
                raise ModelResponseError("Ollama returned an invalid tool call.")
            function = item.get("function")
            if not isinstance(function, dict):
                raise ModelResponseError("Ollama returned an invalid tool function.")
            name = function.get("name")
            arguments = function.get("arguments")
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(arguments, dict)
                or any(not isinstance(key, str) for key in arguments)
            ):
                raise ModelResponseError("Ollama returned invalid tool arguments.")
            calls.append(ModelToolCall(name=name, arguments=dict(arguments)))
        return tuple(calls)
