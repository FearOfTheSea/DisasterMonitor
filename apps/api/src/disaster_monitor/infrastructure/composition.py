"""Manual composition root for the local API."""

from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.llm.ollama_qwen_adapter import OllamaQwenAdapter


def build_language_model(settings: Settings) -> LanguageModel:
    """Construct the configured local model adapter."""
    return OllamaQwenAdapter(
        model_name=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
        max_tokens=settings.ollama_max_tokens,
    )
