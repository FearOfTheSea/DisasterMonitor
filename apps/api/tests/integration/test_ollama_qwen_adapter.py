import json

import httpx
import pytest

from disaster_monitor.application.dto import ModelMessage, ModelRequest, ModelTool
from disaster_monitor.infrastructure.llm.ollama_qwen_adapter import OllamaQwenAdapter


@pytest.mark.asyncio
async def test_adapter_translates_chat_request_and_response() -> None:
    captured_payload = b""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = request.read()
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "Local answer."}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OllamaQwenAdapter(
        model_name="qwen3:1.7b",
        base_url="http://ollama",
        client=client,
    )

    result = await adapter.generate(
        ModelRequest((ModelMessage("user", "Hello"),)),
    )
    await client.aclose()

    assert result.text == "Local answer."
    assert result.model == "qwen3:1.7b"
    assert b'"think":false' in captured_payload


@pytest.mark.asyncio
async def test_adapter_translates_native_function_tools_and_calls() -> None:
    captured_payload = b""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = request.read()
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "fit_country",
                                "arguments": {"country_code": "JPN"},
                            }
                        }
                    ],
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OllamaQwenAdapter("qwen3:1.7b", "http://ollama", client=client)
    result = await adapter.generate(
        ModelRequest(
            (ModelMessage("user", "Zoom into Japan."),),
            tools=(
                ModelTool(
                    "fit_country",
                    "Fit a country.",
                    {
                        "type": "object",
                        "properties": {"country_code": {"type": "string"}},
                    },
                ),
            ),
        )
    )
    await client.aclose()

    payload = json.loads(captured_payload)
    assert payload["tools"][0]["function"]["name"] == "fit_country"
    assert result.text == ""
    assert result.tool_calls[0].name == "fit_country"
    assert result.tool_calls[0].arguments == {"country_code": "JPN"}


@pytest.mark.asyncio
async def test_adapter_readiness_distinguishes_service_and_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:1.7b"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OllamaQwenAdapter("qwen3:1.7b", "http://ollama", client=client)

    readiness = await adapter.check_readiness()
    await client.aclose()

    assert readiness.ollama_available is True
    assert readiness.model_available is True


@pytest.mark.asyncio
async def test_adapter_reports_unavailable_service_without_raising() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OllamaQwenAdapter("qwen3:1.7b", "http://ollama", client=client)

    readiness = await adapter.check_readiness()
    await client.aclose()

    assert readiness.ollama_available is False
    assert readiness.model_available is False
