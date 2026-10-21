"""Adapter for providers implementing the OpenAI-compatible chat API."""

import json
from typing import Any

import httpx

from disaster_monitor.application.dto import (
    ModelReadiness,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from disaster_monitor.domain.errors import ModelResponseError, ModelRuntimeError


class OpenAICompatibleAdapter:
    """Call any configured provider exposing ``/chat/completions``."""

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        max_tokens: int = 512,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds, headers=headers
        )
        self._owns_client = client is None

    async def generate(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": [
                {"role": item.role, "content": item.content}
                for item in request.messages
            ],
            "max_tokens": request.max_tokens or self._max_tokens,
        }
        if request.tools:
            payload["tools"] = [
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
            payload["tool_choice"] = "auto"
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions", json=payload
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ModelRuntimeError(
                "The configured model provider is unavailable or rejected the request."
            ) from error
        body = self._payload(response)
        choices = body.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else None
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            raise ModelResponseError("The model provider returned no chat message.")
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        calls = self._tool_calls(message.get("tool_calls"))
        if not text.strip() and not calls:
            raise ModelResponseError("The model provider returned an empty response.")
        model = body.get("model")
        return ModelResponse(
            text=text.strip(),
            model=model if isinstance(model, str) else self._model_name,
            tool_calls=calls,
        )

    async def check_readiness(self) -> ModelReadiness:
        try:
            response = await self._client.get(f"{self._base_url}/models")
            response.raise_for_status()
            body = self._payload(response)
        except (httpx.HTTPError, ModelResponseError):
            return ModelReadiness(False, False, self._model_name)
        items = body.get("data")
        available = isinstance(items, list) and any(
            isinstance(item, dict) and item.get("id") == self._model_name
            for item in items
        )
        return ModelReadiness(True, available, self._model_name)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

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

    @classmethod
    def _tool_calls(cls, value: object) -> tuple[ModelToolCall, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise ModelResponseError("The model provider returned invalid tool calls.")
        result: list[ModelToolCall] = []
        for item in value:
            function = item.get("function") if isinstance(item, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            arguments = (
                function.get("arguments") if isinstance(function, dict) else None
            )
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError as error:
                    raise ModelResponseError(
                        "The model provider returned invalid tool arguments."
                    ) from error
            if not isinstance(name, str) or not name or not isinstance(arguments, dict):
                raise ModelResponseError(
                    "The model provider returned invalid tool calls."
                )
            result.append(ModelToolCall(name=name, arguments=arguments))
        return tuple(result)
