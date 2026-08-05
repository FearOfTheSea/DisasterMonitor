"""Manual composition root for the local API."""

from disaster_monitor.application.ports.disaster_information import (
    DisasterInformationProvider,
)
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.current_information import (
    google_news_rss_adapter,
)
from disaster_monitor.infrastructure.llm.ollama_qwen_adapter import OllamaQwenAdapter


def build_language_model(settings: Settings) -> LanguageModel:
    """Construct the configured local model adapter."""
    return OllamaQwenAdapter(
        model_name=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
        max_tokens=settings.ollama_max_tokens,
    )


def build_disaster_information_provider(
    settings: Settings,
) -> DisasterInformationProvider:
    """Construct the no-key recent-disaster report adapter."""
    return google_news_rss_adapter.GoogleNewsRssDisasterInformationAdapter(
        base_url=settings.disaster_news_base_url,
        timeout_seconds=settings.disaster_news_timeout_seconds,
        max_items=settings.disaster_news_max_items,
        lookback_days=settings.disaster_news_lookback_days,
    )
