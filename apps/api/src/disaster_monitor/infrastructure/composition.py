"""Manual composition root for the local API."""

from disaster_monitor.application.ports.disaster_information import (
    DisasterEventProvider,
    SituationReportProvider,
)
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
    CompositeSituationReportProvider,
)
from disaster_monitor.infrastructure.disaster.fdma_adapter import (
    FdmaSituationReportAdapter,
)
from disaster_monitor.infrastructure.disaster.jma_adapter import (
    JmaEarthquakeAdapter,
    JmaSignificantEarthquakeAdapter,
    JmaTsunamiSituationAdapter,
)
from disaster_monitor.infrastructure.disaster.reliefweb_adapter import (
    ReliefWebSituationAdapter,
)
from disaster_monitor.infrastructure.disaster.usgs_adapter import UsgsEarthquakeAdapter
from disaster_monitor.infrastructure.llm.ollama_qwen_adapter import OllamaQwenAdapter


def build_language_model(settings: Settings) -> LanguageModel:
    """Construct the configured local model adapter."""
    return OllamaQwenAdapter(
        model_name=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
        max_tokens=settings.ollama_max_tokens,
    )


def build_current_disaster_report(settings: Settings) -> CurrentDisasterReportService:
    """Construct the small live provider set used by current earthquake reports."""
    event_provider: DisasterEventProvider = CompositeDisasterEventProvider(
        (
            JmaEarthquakeAdapter(
                timeout_seconds=settings.disaster_provider_timeout_seconds,
                max_response_bytes=settings.disaster_provider_max_response_bytes,
            ),
            JmaSignificantEarthquakeAdapter(
                timeout_seconds=settings.disaster_provider_timeout_seconds,
                max_response_bytes=settings.disaster_provider_max_response_bytes,
            ),
            UsgsEarthquakeAdapter(
                timeout_seconds=settings.disaster_provider_timeout_seconds,
                max_response_bytes=settings.disaster_provider_max_response_bytes,
            ),
        )
    )
    situation_providers: list[SituationReportProvider] = [
        FdmaSituationReportAdapter(
            timeout_seconds=settings.disaster_provider_timeout_seconds,
            max_response_bytes=settings.disaster_provider_max_response_bytes,
        ),
        JmaTsunamiSituationAdapter(
            timeout_seconds=settings.disaster_provider_timeout_seconds,
            max_response_bytes=settings.disaster_provider_max_response_bytes,
        ),
    ]
    if (
        settings.reliefweb_app_name
        and settings.reliefweb_app_name.strip().lower()
        not in {
            "disaster-monitor-local",
            "change-me",
            "your-app-name",
        }
    ):
        situation_providers.append(
            ReliefWebSituationAdapter(
                app_name=settings.reliefweb_app_name,
                timeout_seconds=settings.disaster_provider_timeout_seconds,
                max_response_bytes=settings.disaster_provider_max_response_bytes,
            )
        )
    situation_provider: SituationReportProvider = CompositeSituationReportProvider(
        tuple(situation_providers)
    )
    return CurrentDisasterReportService(event_provider, situation_provider)
