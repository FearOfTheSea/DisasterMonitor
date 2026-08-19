import base64
import json
from datetime import UTC, datetime

import httpx
import pytest

from disaster_monitor.application.multimodal import (
    AssetAdmissionInput,
    VisualAnalysisRequest,
)
from disaster_monitor.application.services.multimodal_asset_admission import (
    MultimodalAssetAdmissionService,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.errors import ModelResponseError
from disaster_monitor.domain.multimodal import CaptureRole, DamageLevel
from disaster_monitor.infrastructure.vision.ollama_vision_adapter import (
    ADAPTER_VERSION,
    OllamaVisionAdapter,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _asset():
    return MultimodalAssetAdmissionService(clock=lambda: NOW).admit(
        AssetAdmissionInput(
            content=PNG,
            attribution="Adapter unit fixture",
            captured_at=NOW,
            footprint_coordinates=(((0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.0)),),
            declared_disaster=Disaster.EARTHQUAKE,
            declared_country_code="JPN",
            capture_role=CaptureRole.SINGLE_CAPTURE,
            processing_level="raw",
        )
    )


@pytest.mark.asyncio
async def test_adapter_accepts_strict_json_from_ollama_thinking_field() -> None:
    prediction = {
        "damage_level": "major_damage",
        "damage_confidence": 0.81,
        "damage_cues": ["collapsed roof"],
        "answer": "a roof is collapsed",
        "answerable": True,
        "answer_confidence": 0.78,
        "answer_cues": ["roof discontinuity"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen3-vl:2b",
                            "digest": "sha256:real-model-digest",
                        }
                    ]
                },
            )
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3-vl:2b"
        assert payload["think"] is False
        assert payload["options"] == {
            "num_predict": 384,
            "temperature": 0.0,
            "seed": 7,
        }
        serialized = json.dumps(payload).casefold()
        assert "dataset_family" not in serialized
        assert "sample_id" not in serialized
        return httpx.Response(
            200,
            json={
                "model": "qwen3-vl:2b",
                "message": {"content": "", "thinking": json.dumps(prediction)},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OllamaVisionAdapter("qwen3-vl:2b", "http://ollama.test", client=client)
    try:
        readiness = await adapter.check_readiness()
        result = await adapter.analyze(
            VisualAnalysisRequest(_asset(), "What visible damage is present?")
        )
    finally:
        await client.aclose()

    assert readiness.model_available
    assert readiness.model_digest == "sha256:real-model-digest"
    assert result.damage_level == DamageLevel.MAJOR_DAMAGE
    assert result.configuration.adapter_version == ADAPTER_VERSION
    assert result.configuration.model_digest == "sha256:real-model-digest"


@pytest.mark.asyncio
async def test_adapter_rejects_non_json_content_and_thinking() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3-vl:2b",
                "message": {"content": "", "thinking": "not JSON"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OllamaVisionAdapter("qwen3-vl:2b", "http://ollama.test", client=client)
    try:
        with pytest.raises(ModelResponseError, match="invalid visual JSON"):
            await adapter.analyze(VisualAnalysisRequest(_asset(), None))
    finally:
        await client.aclose()
