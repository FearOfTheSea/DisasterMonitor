"""Focused Ollama adapter for deterministic local vision-language analysis."""

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
    VISUAL_ANALYSIS_PROMPT_VERSION,
    VISUAL_ANALYSIS_SYSTEM_PROMPT,
    visual_analysis_prompt,
)
from disaster_monitor.domain.errors import ModelResponseError, ModelRuntimeError
from disaster_monitor.domain.multimodal import (
    DamageLevel,
    VisualAnalysisConfiguration,
)

ADAPTER_VERSION = "ollama-vision-adapter-v2"
ANALYSIS_VERSION = "bounded-damage-vqa-v1"
PREPROCESSING_VERSION = "original-png-jpeg-bytes-v1"
TEMPERATURE = 0.0
SEED = 7

_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "damage_level",
        "damage_confidence",
        "damage_cues",
        "answer",
        "answerable",
        "answer_confidence",
        "answer_cues",
    ],
    "properties": {
        "damage_level": {
            "type": "string",
            "enum": [item.value for item in DamageLevel],
        },
        "damage_confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "damage_cues": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "maxLength": 160},
        },
        "answer": {"type": ["string", "null"], "maxLength": 200},
        "answerable": {"type": "boolean"},
        "answer_confidence": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 1,
        },
        "answer_cues": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "maxLength": 160},
        },
    },
}


class OllamaVisionAdapter:
    """Use one configured local VLM without exposing model choice to the agent."""

    def __init__(
        self,
        model_name: str,
        base_url: str,
        *,
        timeout_seconds: float = 180.0,
        max_tokens: int = 384,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._model_digest: str | None = None

    async def analyze(self, request: VisualAnalysisRequest) -> VisualModelPrediction:
        encoded = base64.b64encode(request.asset.content).decode("ascii")
        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model_name,
                    "messages": [
                        {"role": "system", "content": VISUAL_ANALYSIS_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": visual_analysis_prompt(request.question),
                            "images": [encoded],
                        },
                    ],
                    "format": _OUTPUT_SCHEMA,
                    "stream": False,
                    "think": False,
                    "options": {
                        "num_predict": self._max_tokens,
                        "temperature": TEMPERATURE,
                        "seed": SEED,
                    },
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ModelRuntimeError(
                "The configured local visual model is unavailable."
            ) from error
        payload = _payload(response)
        if payload.get("model") not in {None, self._model_name}:
            raise ModelResponseError("Ollama returned an unexpected visual model ID.")
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        thinking = message.get("thinking") if isinstance(message, dict) else None
        structured_content = (
            content
            if isinstance(content, str) and content.strip()
            else thinking
            if isinstance(thinking, str) and thinking.strip()
            else None
        )
        if structured_content is None:
            raise ModelResponseError("Ollama returned no visual JSON content.")
        try:
            item = json.loads(structured_content)
        except json.JSONDecodeError as error:
            raise ModelResponseError("Ollama returned invalid visual JSON.") from error
        return self._prediction(item)

    async def check_readiness(self) -> VisualModelReadiness:
        try:
            response = await self._client.get(f"{self._base_url}/api/tags")
            response.raise_for_status()
            payload = _payload(response)
        except (httpx.HTTPError, ModelResponseError):
            return self._readiness(False, False)
        models = payload.get("models")
        match = (
            next(
                (
                    item
                    for item in models
                    if isinstance(models, list)
                    and isinstance(item, dict)
                    and item.get("name") == self._model_name
                ),
                None,
            )
            if isinstance(models, list)
            else None
        )
        digest = match.get("digest") if isinstance(match, dict) else None
        self._model_digest = digest if isinstance(digest, str) else None
        return self._readiness(True, match is not None)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _readiness(
        self, runtime_available: bool, model_available: bool
    ) -> VisualModelReadiness:
        return VisualModelReadiness(
            runtime_available=runtime_available,
            model_available=model_available,
            model_id=self._model_name,
            model_digest=self._model_digest,
            adapter_version=ADAPTER_VERSION,
            prompt_version=VISUAL_ANALYSIS_PROMPT_VERSION,
            preprocessing_version=PREPROCESSING_VERSION,
        )

    def _prediction(self, item: object) -> VisualModelPrediction:
        if not isinstance(item, dict) or set(item) != set(_OUTPUT_SCHEMA["required"]):
            raise ModelResponseError("The visual result has an invalid shape.")
        try:
            damage_level = DamageLevel(item["damage_level"])
        except (ValueError, TypeError) as error:
            raise ModelResponseError("The visual damage label is invalid.") from error
        damage_confidence = _confidence(item["damage_confidence"])
        answer_confidence = _confidence(item["answer_confidence"])
        answer = item["answer"]
        answerable = item["answerable"]
        if answer is not None and (not isinstance(answer, str) or len(answer) > 200):
            raise ModelResponseError("The visual answer is invalid.")
        if not isinstance(answerable, bool):
            raise ModelResponseError("The visual answerability flag is invalid.")
        if not answerable and (answer is not None or answer_confidence is not None):
            raise ModelResponseError("An unanswerable visual result must abstain.")
        return VisualModelPrediction(
            damage_level=damage_level,
            damage_confidence=damage_confidence,
            damage_cues=_cues(item["damage_cues"]),
            answer=answer.strip() if isinstance(answer, str) else None,
            answerable=answerable,
            answer_confidence=answer_confidence,
            answer_cues=_cues(item["answer_cues"]),
            configuration=VisualAnalysisConfiguration(
                model_id=self._model_name,
                model_digest=self._model_digest,
                adapter_version=ADAPTER_VERSION,
                analysis_version=ANALYSIS_VERSION,
                prompt_version=VISUAL_ANALYSIS_PROMPT_VERSION,
                preprocessing_version=PREPROCESSING_VERSION,
                maximum_output_tokens=self._max_tokens,
                temperature=TEMPERATURE,
                seed=SEED,
            ),
        )


def _payload(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise ModelResponseError("Ollama returned invalid JSON.") from error
    if not isinstance(payload, dict):
        raise ModelResponseError("Ollama returned an invalid response payload.")
    return payload


def _confidence(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ModelResponseError("Visual confidence must be numeric or null.")
    result = float(value)
    if not 0 <= result <= 1:
        raise ModelResponseError("Visual confidence is outside zero through one.")
    return result


def _cues(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) > 4
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 160
            for item in value
        )
    ):
        raise ModelResponseError("Visual cues must be bounded non-empty strings.")
    return tuple(item.strip() for item in value)
