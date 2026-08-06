"""Manual composition root for the local API."""

from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
)
from disaster_monitor.application.services.source_consistency import (
    validate_provider_source_consistency,
)
from disaster_monitor.domain.disaster import Hazard
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
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.llm.ollama_qwen_adapter import OllamaQwenAdapter
from disaster_monitor.infrastructure.llm.structured_agent_model import (
    StructuredAgentModel,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)


def build_language_model(settings: Settings) -> LanguageModel:
    """Construct the configured local model adapter."""
    return OllamaQwenAdapter(
        model_name=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
        max_tokens=settings.ollama_max_tokens,
    )


def build_agent_model(settings: Settings) -> AgentModel:
    """Construct a separate structured-agent abstraction over local Qwen."""
    return StructuredAgentModel(build_language_model(settings))


def build_source_catalog(settings: Settings | None = None) -> StaticSourceCatalog:
    """Construct the packaged maintained disaster-source catalog."""
    if settings is None:
        return StaticSourceCatalog()
    name = (settings.reliefweb_app_name or "").strip().lower()
    configured = bool(
        name and name not in {"disaster-monitor-local", "change-me", "your-app-name"}
    )
    return StaticSourceCatalog({"reliefweb-situation-reports": configured})


def build_country_catalog() -> StaticCountryCatalog:
    """Construct the packaged deterministic country/geography adapter."""
    return StaticCountryCatalog()


def build_disaster_query_parser(
    country_catalog: StaticCountryCatalog | None = None,
) -> DisasterQueryParser:
    """Construct deterministic disaster parsing with packaged country metadata."""
    return DisasterQueryParser(country_catalog or build_country_catalog())


def build_current_disaster_report(
    settings: Settings,
    country_catalog: StaticCountryCatalog | None = None,
) -> CurrentDisasterReportService:
    """Construct capability-registered live disaster providers."""
    jma_rolling = JmaEarthquakeAdapter(
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    jma_significant = JmaSignificantEarthquakeAdapter(
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    geography = country_catalog or build_country_catalog()
    usgs = UsgsEarthquakeAdapter(
        geography=geography,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    fdma = FdmaSituationReportAdapter(
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    jma_tsunami = JmaTsunamiSituationAdapter(
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    reliefweb = ReliefWebSituationAdapter(
        app_name=settings.reliefweb_app_name,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    event_japan = ProviderCapabilities(
        roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
        hazards=frozenset({Hazard.EARTHQUAKE}),
        country_codes=frozenset({"JPN"}),
    )
    situation_japan = ProviderCapabilities(
        roles=frozenset({ProviderRole.SITUATION_EVIDENCE}),
        hazards=frozenset({Hazard.EARTHQUAKE}),
        country_codes=frozenset({"JPN"}),
    )
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "JMA rolling earthquake",
                jma_rolling,
                event_japan,
                source_id="jma-rolling-earthquakes",
            ),
            ProviderRegistration(
                "JMA significant earthquake",
                jma_significant,
                event_japan,
                source_id="jma-significant-earthquakes",
            ),
            ProviderRegistration(
                "USGS",
                usgs,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    hazards=frozenset({Hazard.EARTHQUAKE}),
                    country_codes=None,
                ),
                source_id="usgs-earthquakes",
            ),
            ProviderRegistration(
                "FDMA",
                fdma,
                situation_japan,
                source_id="fdma-situation-reports",
            ),
            ProviderRegistration(
                "JMA tsunami status",
                jma_tsunami,
                situation_japan,
                source_id="jma-tsunami-status",
                event_eligibility=lambda event: event.jma_event_id is not None,
            ),
            ProviderRegistration(
                "ReliefWeb",
                reliefweb,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    hazards=frozenset(Hazard),
                    country_codes=None,
                    requires_configuration=True,
                ),
                source_id="reliefweb-situation-reports",
                configured=reliefweb.configured,
            ),
        )
    )
    source_catalog = StaticSourceCatalog(
        {"reliefweb-situation-reports": reliefweb.configured}
    )
    validate_provider_source_consistency(registry, source_catalog)
    event_provider = CompositeDisasterEventProvider(registry)
    situation_provider = CompositeSituationReportProvider(registry)
    return CurrentDisasterReportService(
        event_provider,
        situation_provider,
        provider_registry=registry,
        event_policies=default_event_policy_registry(),
        evidence_reconciler=EvidenceReconciler(),
        renderer=DisasterReportRenderer(),
        source_catalog=source_catalog,
    )
