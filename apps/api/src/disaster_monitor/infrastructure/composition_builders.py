"""Manual composition root for the local API."""

from collections.abc import Callable
from datetime import datetime, timedelta

from disaster_monitor.application.agent.operator_actions import OPERATOR_ACTION_IDS
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.conversation_deletion import (
    ConversationDeletionStore,
)
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.memory_store import MemoryStore
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.specialist_model import SpecialistModel
from disaster_monitor.application.ports.visual_analysis import VisualAnalyzer
from disaster_monitor.application.satellite_imagery import SatelliteImageryService
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.services.event_media import DisasterMediaService
from disaster_monitor.application.services.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.services.memory_recall import MemoryRecallService
from disaster_monitor.application.services.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.services.operational_ingestion import (
    SnapshotPersistenceService,
)
from disaster_monitor.application.services.provider_registry import (
    ProviderRegistry,
)
from disaster_monitor.application.services.source_consistency import (
    validate_provider_source_consistency,
)
from disaster_monitor.application.services.source_evidence_policy import (
    validate_event_evidence,
    validate_situation_evidence,
)
from disaster_monitor.application.services.specialist_executor import (
    SpecialistExecutor,
)
from disaster_monitor.application.weather_alerts import WeatherAlertsService
from disaster_monitor.infrastructure.composition_models import (
    EventMediaServices,
    OperationalServices,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.conversations.deletion_store import (
    InMemoryConversationDeletionStore,
    PostgresConversationDeletionStore,
)
from disaster_monitor.infrastructure.conversations.memory_repository import (
    InMemoryConversationRepository,
)
from disaster_monitor.infrastructure.conversations.postgres_repository import (
    PostgresConversationRepository,
)
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
    CompositeSituationReportProvider,
)
from disaster_monitor.infrastructure.disaster.http import SourcePayloadRecorder
from disaster_monitor.infrastructure.disaster.registrations import (
    build_provider_registrations,
)
from disaster_monitor.infrastructure.geography.country_catalog_updates import (
    AutonomousCountryCatalogUpdater,
    CountryCatalogAutomation,
    NaturalEarthCountryCatalogSource,
    VersionedCountryCatalogStore,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.llm.ollama_qwen_adapter import OllamaQwenAdapter
from disaster_monitor.infrastructure.llm.structured_agent_model import (
    StructuredAgentModel,
)
from disaster_monitor.infrastructure.llm.structured_specialist_model import (
    StructuredSpecialistModel,
)
from disaster_monitor.infrastructure.media.filesystem_store import (
    FilesystemMediaAssetStore,
)
from disaster_monitor.infrastructure.media.news_scraper import NewsEventMediaProvider
from disaster_monitor.infrastructure.memory.memory_repository import (
    InMemoryMemoryRepository,
)
from disaster_monitor.infrastructure.memory.postgres_repository import (
    PostgresMemoryRepository,
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
from disaster_monitor.infrastructure.satellite_imagery.providers import (
    NasaGibsImageryProvider,
    PlanetImageryProvider,
    SentinelHubImageryProvider,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)
from disaster_monitor.infrastructure.vision.ollama_vision_adapter import (
    OllamaVisionAdapter,
)
from disaster_monitor.infrastructure.weather.nws_alerts import NwsWeatherAlertsAdapter


def build_event_media_services(
    settings: Settings, *, clock: Callable[[], datetime]
) -> EventMediaServices:
    store = FilesystemMediaAssetStore(
        settings.event_media_blob_root,
        maximum_bytes=settings.event_media_store_maximum_bytes,
    )
    if not settings.event_media_enabled:
        return EventMediaServices(None, store)
    provider = NewsEventMediaProvider(
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        maximum_page_bytes=settings.disaster_provider_max_response_bytes,
        maximum_image_bytes=settings.event_media_max_image_bytes,
        candidate_limit=settings.event_media_candidate_limit,
    )
    return EventMediaServices(
        DisasterMediaService(
            (provider,),
            store,
            clock=clock,
            target_count=settings.event_media_target_count,
        ),
        store,
    )


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


def build_conversation_repository(
    settings: Settings,
    repository: ConversationStore | None = None,
) -> ConversationStore:
    """Build durable PostgreSQL conversations or the local fallback."""
    if repository is not None:
        return repository
    dsn = (
        settings.operational_database_url.get_secret_value()
        if settings.operational_database_url is not None
        else ""
    )
    return (
        PostgresConversationRepository(dsn) if dsn else InMemoryConversationRepository()
    )


def build_memory_repository(
    settings: Settings,
    repository: MemoryStore | None = None,
) -> MemoryStore:
    """Build typed PostgreSQL historical memory or the local fallback."""
    if repository is not None:
        return repository
    dsn = (
        settings.operational_database_url.get_secret_value()
        if settings.operational_database_url is not None
        else ""
    )
    return PostgresMemoryRepository(dsn) if dsn else InMemoryMemoryRepository()


def build_conversation_deletion_store(
    conversations: ConversationStore,
    memories: MemoryStore,
) -> ConversationDeletionStore:
    """Use FK cascade in PostgreSQL and one staged mutation in memory."""
    if (
        type(conversations) is InMemoryConversationRepository
        and type(memories) is InMemoryMemoryRepository
    ):
        return InMemoryConversationDeletionStore(
            conversations,
            memories,
        )
    if (
        type(conversations) is PostgresConversationRepository
        and type(memories) is PostgresMemoryRepository
    ):
        return PostgresConversationDeletionStore(
            conversations,
            memories,
        )
    raise ValueError(
        "Repositories do not share an atomic conversation deletion boundary. "
        "Provide an explicit conversation deletion store for custom persistence."
    )


def build_language_model(settings: Settings) -> LanguageModel:
    """Construct the configured local model adapter."""
    return OllamaQwenAdapter(
        model_name=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_timeout_seconds,
        max_tokens=settings.ollama_max_tokens,
    )


def build_agent_model(
    settings: Settings, language_model: LanguageModel | None = None
) -> AgentModel:
    """Construct a separate structured-agent abstraction over local Qwen."""
    operator_action_ids = tuple(sorted(OPERATOR_ACTION_IDS))
    if language_model is not None:
        return StructuredAgentModel(
            language_model,
            operator_action_ids=operator_action_ids,
        )
    return StructuredAgentModel(
        build_language_model(settings),
        owns_language_model=True,
        operator_action_ids=operator_action_ids,
    )


def build_specialist_model(language_model: LanguageModel) -> SpecialistModel:
    """Wrap the configured text model without constructing another model adapter."""
    return StructuredSpecialistModel(language_model)


def build_visual_analyzer(settings: Settings) -> VisualAnalyzer:
    """Construct the lazy local-only visual analysis adapter."""
    return OllamaVisionAdapter(
        model_name=settings.ollama_vision_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.ollama_vision_timeout_seconds,
        max_tokens=settings.ollama_vision_max_tokens,
    )


def build_satellite_imagery_service(settings: Settings) -> SatelliteImageryService:
    """Construct the direct GIBS catalog and fixed protected tile adapters."""
    sentinel_instance_id = (
        settings.copernicus_sentinel_hub_instance_id.get_secret_value()
        if settings.copernicus_sentinel_hub_instance_id is not None
        else None
    )
    planet_api_key = (
        settings.planet_api_key.get_secret_value()
        if settings.planet_api_key is not None
        else None
    )
    return SatelliteImageryService(
        (
            NasaGibsImageryProvider(),
            SentinelHubImageryProvider(
                instance_id=sentinel_instance_id,
                layer_id=settings.copernicus_sentinel_hub_layer_id,
                timeout_seconds=settings.disaster_provider_timeout_seconds,
                maximum_response_bytes=(settings.disaster_provider_max_response_bytes),
            ),
            PlanetImageryProvider(
                api_key=planet_api_key,
                mosaic_name=settings.planet_mosaic_name,
                timeout_seconds=settings.disaster_provider_timeout_seconds,
                maximum_response_bytes=(settings.disaster_provider_max_response_bytes),
            ),
        )
    )


def build_weather_alerts_service(
    settings: Settings,
    *,
    snapshot_recorder: SourcePayloadRecorder | None = None,
) -> WeatherAlertsService:
    """Construct the separately registered authoritative warning provider."""
    return WeatherAlertsService(
        NwsWeatherAlertsAdapter(
            snapshot_recorder=snapshot_recorder,
            timeout_seconds=settings.disaster_provider_timeout_seconds,
            maximum_response_bytes=settings.weather_alert_max_response_bytes,
            maximum_records=settings.weather_alert_max_records,
        )
    )


def build_source_catalog(settings: Settings | None = None) -> StaticSourceCatalog:
    """Construct the packaged maintained global disaster-source catalog."""
    if settings is None:
        return StaticSourceCatalog()
    app_name = (settings.reliefweb_app_name or "").strip().lower()
    configured = bool(
        app_name
        and app_name not in {"disaster-monitor-local", "change-me", "your-app-name"}
    )
    firms_key = (
        settings.nasa_firms_map_key.get_secret_value().strip()
        if settings.nasa_firms_map_key is not None
        else ""
    )
    firms_configured = (
        len(firms_key) >= 8
        and len(firms_key) <= 200
        and all(character.isalnum() or character in "_-" for character in firms_key)
    )
    return StaticSourceCatalog(
        {
            "reliefweb-situation-reports": configured,
            "nasa-firms-observations": firms_configured,
        }
    )


def build_country_catalog(settings: Settings | None = None) -> StaticCountryCatalog:
    """Construct the packaged-fallback and runtime-refresh geography adapter."""
    root = settings.country_catalog_root if settings is not None else None
    return StaticCountryCatalog(root)


def build_country_catalog_automation(
    settings: Settings,
    country_catalog: StaticCountryCatalog,
) -> CountryCatalogAutomation:
    """Construct the fail-closed monthly and on-request catalog updater."""
    source = NaturalEarthCountryCatalogSource(
        timeout_seconds=settings.country_catalog_update_timeout_seconds,
        max_response_bytes=settings.country_catalog_max_response_bytes,
    )
    updater = AutonomousCountryCatalogUpdater(
        catalog=country_catalog,
        store=VersionedCountryCatalogStore(
            settings.country_catalog_root, country_catalog
        ),
        source=source,
        automatic_updates_enabled=settings.country_catalog_automatic_updates,
    )
    return CountryCatalogAutomation(
        updater,
        automatic_updates_enabled=settings.country_catalog_automatic_updates,
        retry_interval=timedelta(hours=settings.country_catalog_retry_hours),
    )


def build_disaster_query_parser(
    country_catalog: StaticCountryCatalog | None = None,
) -> DisasterQueryParser:
    """Construct deterministic disaster parsing with active country metadata."""
    return DisasterQueryParser(country_catalog or build_country_catalog())


def build_current_disaster_report(
    settings: Settings,
    country_catalog: StaticCountryCatalog | None = None,
    snapshot_recorder: SourcePayloadRecorder | None = None,
    operational_evidence: OperationalEvidenceRecorder | None = None,
    specialist_executor: SpecialistExecutor | None = None,
    memory_recall: MemoryRecallService | None = None,
) -> CurrentDisasterReportService:
    """Construct capability-registered live disaster providers."""
    geography = country_catalog or build_country_catalog()
    registry = ProviderRegistry(
        build_provider_registrations(settings, geography, snapshot_recorder)
    )
    source_catalog = build_source_catalog(settings)
    validate_provider_source_consistency(registry, source_catalog)
    event_provider = CompositeDisasterEventProvider(
        registry, validate=validate_event_evidence
    )
    situation_provider = CompositeSituationReportProvider(
        registry, validate=validate_situation_evidence
    )
    return CurrentDisasterReportService(
        event_provider,
        situation_provider,
        provider_registry=registry,
        event_policies=default_event_policy_registry(),
        evidence_reconciler=EvidenceReconciler(),
        renderer=DisasterReportRenderer(),
        source_catalog=source_catalog,
        operational_evidence=operational_evidence,
        specialist_executor=specialist_executor,
        memory_recall=memory_recall,
    )
