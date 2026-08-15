"""Manual composition root for the local API."""

from dataclasses import dataclass

from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.visual_analysis import VisualAnalyzer
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
from disaster_monitor.application.services.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.services.operational_ingestion import (
    SnapshotPersistenceService,
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
from disaster_monitor.infrastructure.disaster.firms_adapter import (
    FirmsActiveFireAdapter,
)
from disaster_monitor.infrastructure.disaster.gfm_adapter import (
    GfmFloodNotificationAdapter,
)
from disaster_monitor.infrastructure.disaster.http import SourcePayloadRecorder
from disaster_monitor.infrastructure.disaster.jma_adapter import (
    JmaEarthquakeAdapter,
    JmaSignificantEarthquakeAdapter,
    JmaTsunamiSituationAdapter,
)
from disaster_monitor.infrastructure.disaster.nchmf_adapter import NchmfWarningAdapter
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
from disaster_monitor.infrastructure.operations.filesystem_blob_store import (
    FilesystemBlobStore,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)
from disaster_monitor.infrastructure.vision.ollama_vision_adapter import (
    OllamaVisionAdapter,
)


@dataclass(frozen=True, slots=True)
class OperationalServices:
    """Explicit operational persistence dependencies for API composition."""

    repository: OperationalRepository
    snapshots: SnapshotPersistenceService
    evidence: OperationalEvidenceRecorder


def build_operational_services(
    settings: Settings,
    repository: OperationalRepository | None = None,
) -> OperationalServices:
    """Build PostgreSQL-backed services or a transparent local in-process fallback."""
    configured_repository = repository
    if configured_repository is None:
        dsn = (
            settings.operational_database_url.get_secret_value()
            if settings.operational_database_url is not None
            else ""
        )
        configured_repository = (
            PostgresOperationalRepository(dsn)
            if dsn
            else InMemoryOperationalRepository()
        )
    persistence = SnapshotPersistenceService(
        configured_repository,
        FilesystemBlobStore(settings.operational_blob_root),
    )
    return OperationalServices(
        configured_repository,
        persistence,
        OperationalEvidenceRecorder(configured_repository),
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


def build_visual_analyzer(settings: Settings) -> VisualAnalyzer:
    """Construct the lazy local-only visual analysis adapter."""
    return OllamaVisionAdapter(
        model_name=settings.ollama_vision_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_vision_timeout_seconds,
        max_tokens=settings.ollama_vision_max_tokens,
    )


def build_source_catalog(settings: Settings | None = None) -> StaticSourceCatalog:
    """Construct the packaged maintained disaster-source catalog."""
    if settings is None:
        return StaticSourceCatalog()
    name = (settings.reliefweb_app_name or "").strip().lower()
    configured = bool(
        name and name not in {"disaster-monitor-local", "change-me", "your-app-name"}
    )
    return StaticSourceCatalog(
        {
            "reliefweb-situation-reports": configured,
            "nasa-firms-active-fire": bool(
                settings.firms_map_key is not None
                and settings.firms_map_key.get_secret_value().strip()
            ),
            "copernicus-gfm-vietnam": bool(
                settings.gfm_access_token is not None
                and settings.gfm_access_token.get_secret_value().strip()
                and settings.gfm_user_id
            ),
        }
    )


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
    snapshot_recorder: SourcePayloadRecorder | None = None,
    operational_evidence: OperationalEvidenceRecorder | None = None,
) -> CurrentDisasterReportService:
    """Construct capability-registered live disaster providers."""
    jma_rolling = JmaEarthquakeAdapter(
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    jma_significant = JmaSignificantEarthquakeAdapter(
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    geography = country_catalog or build_country_catalog()
    usgs = UsgsEarthquakeAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    fdma = FdmaSituationReportAdapter(
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    jma_tsunami = JmaTsunamiSituationAdapter(
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    reliefweb = ReliefWebSituationAdapter(
        app_name=settings.reliefweb_app_name,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    nchmf = NchmfWarningAdapter(
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    firms = FirmsActiveFireAdapter(
        geography=geography,
        map_key=(
            settings.firms_map_key.get_secret_value()
            if settings.firms_map_key is not None
            else None
        ),
        dataset=settings.firms_dataset,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    gfm = GfmFloodNotificationAdapter(
        access_token=(
            settings.gfm_access_token.get_secret_value()
            if settings.gfm_access_token is not None
            else None
        ),
        user_id=settings.gfm_user_id,
        snapshot_recorder=snapshot_recorder,
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
                allowed_hosts=jma_rolling.allowed_hosts,
            ),
            ProviderRegistration(
                "JMA significant earthquake",
                jma_significant,
                event_japan,
                source_id="jma-significant-earthquakes",
                allowed_hosts=jma_significant.allowed_hosts,
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
                allowed_hosts=usgs.allowed_hosts,
            ),
            ProviderRegistration(
                "FDMA",
                fdma,
                situation_japan,
                source_id="fdma-situation-reports",
                allowed_hosts=fdma.allowed_hosts,
            ),
            ProviderRegistration(
                "JMA tsunami status",
                jma_tsunami,
                situation_japan,
                source_id="jma-tsunami-status",
                event_eligibility=lambda event: event.jma_event_id is not None,
                allowed_hosts=jma_tsunami.allowed_hosts,
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
                allowed_hosts=reliefweb.allowed_hosts,
            ),
            ProviderRegistration(
                "NCHMF Vietnam warnings",
                nchmf,
                ProviderCapabilities(
                    roles=frozenset(
                        {
                            ProviderRole.EVENT_DISCOVERY,
                            ProviderRole.SITUATION_EVIDENCE,
                        }
                    ),
                    hazards=frozenset(
                        {
                            Hazard.FLOOD,
                            Hazard.LANDSLIDE,
                            Hazard.TROPICAL_CYCLONE,
                        }
                    ),
                    country_codes=frozenset({"VNM"}),
                ),
                source_id="nchmf-vietnam-warnings",
                allowed_hosts=nchmf.allowed_hosts,
            ),
            ProviderRegistration(
                "NASA FIRMS active fire",
                firms,
                ProviderCapabilities(
                    roles=frozenset(
                        {
                            ProviderRole.EVENT_DISCOVERY,
                            ProviderRole.SITUATION_EVIDENCE,
                        }
                    ),
                    hazards=frozenset({Hazard.WILDFIRE}),
                    country_codes=None,
                    requires_configuration=True,
                ),
                source_id="nasa-firms-active-fire",
                configured=firms.configured,
                allowed_hosts=firms.allowed_hosts,
            ),
            ProviderRegistration(
                "Copernicus GFM Vietnam notifications",
                gfm,
                ProviderCapabilities(
                    roles=frozenset(
                        {
                            ProviderRole.EVENT_DISCOVERY,
                            ProviderRole.SITUATION_EVIDENCE,
                        }
                    ),
                    hazards=frozenset({Hazard.FLOOD}),
                    country_codes=frozenset({"VNM"}),
                    requires_configuration=True,
                ),
                source_id="copernicus-gfm-vietnam",
                configured=gfm.configured,
                allowed_hosts=gfm.allowed_hosts,
            ),
        )
    )
    source_catalog = StaticSourceCatalog(
        {
            "reliefweb-situation-reports": reliefweb.configured,
            "nasa-firms-active-fire": firms.configured,
            "copernicus-gfm-vietnam": gfm.configured,
        }
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
        operational_evidence=operational_evidence,
    )
