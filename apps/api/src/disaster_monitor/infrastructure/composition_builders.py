"""Manual composition root for the local API."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.agent.operator_actions import OPERATOR_ACTION_IDS
from disaster_monitor.application.agent.tooling import (
    DisasterToolDependencies,
    build_disaster_tool_registry,
)
from disaster_monitor.application.conversations.memory_recall import MemoryRecallService
from disaster_monitor.application.earthquake_context import EarthquakeContextService
from disaster_monitor.application.evidence.event_resolution import (
    default_event_policy_registry,
)
from disaster_monitor.application.evidence.evidence_reconciliation import (
    EvidenceReconciler,
)
from disaster_monitor.application.evidence.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.evidence.snapshot_persistence import (
    SnapshotPersistenceService,
)
from disaster_monitor.application.evidence.source_consistency import (
    validate_provider_source_consistency,
)
from disaster_monitor.application.evidence.source_evidence_policy import (
    validate_event_evidence,
    validate_situation_evidence,
)
from disaster_monitor.application.ground_imagery.resolve_region import (
    GroundImageryRegionResolver,
)
from disaster_monitor.application.ground_imagery.service import GroundImageryService
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.imagery_context import (
    ActiveIncidentImageryContextReader,
    EarthquakeProductImageryContextReader,
)
from disaster_monitor.application.investigation.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.investigation.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.investigation.disaster_report_renderer import (
    DisasterReportRenderer,
)
from disaster_monitor.application.investigation.specialist_executor import (
    SpecialistExecutor,
)
from disaster_monitor.application.investigation.workflow import (
    DisasterInvestigationWorkflow,
)
from disaster_monitor.application.media_analysis.event_media import DisasterMediaService
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.conversation_deletion import (
    ConversationDeletionStore,
)
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.ports.ground_imagery.incidents import (
    IncidentImageryContextReader,
)
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.memory_store import MemoryStore
from disaster_monitor.application.ports.news import BreakingNewsFeed
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.specialist_model import SpecialistModel
from disaster_monitor.application.ports.visual_analysis import VisualAnalyzer
from disaster_monitor.application.ports.weather_alerts import WeatherAlertProvider
from disaster_monitor.application.ports.web_collection import WebCollectionStore
from disaster_monitor.application.satellite_imagery import SatelliteImageryService
from disaster_monitor.application.sources.provider_registry import (
    ProviderRegistry,
)
from disaster_monitor.application.weather_alerts import WeatherAlertsService
from disaster_monitor.infrastructure.app_dependencies import AppLifecycle
from disaster_monitor.infrastructure.composition_models import (
    EventMediaServices,
    InvestigationResources,
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
from disaster_monitor.infrastructure.earthquake.usgs_products import (
    UsgsEarthquakeProductsAdapter,
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
from disaster_monitor.infrastructure.ground_imagery.artifact_store import (
    FilesystemImageryArtifactStore,
)
from disaster_monitor.infrastructure.ground_imagery.cdse_catalog import CDSEStacCatalog
from disaster_monitor.infrastructure.ground_imagery.geoboundaries import (
    GeoBoundariesPlaceLookup,
)
from disaster_monitor.infrastructure.ground_imagery.geometry import (
    GeodesicGeometryEngine,
)
from disaster_monitor.infrastructure.ground_imagery.local_products import (
    FallbackGroundImageryRenderer,
    PublicCogRenderer,
)
from disaster_monitor.infrastructure.ground_imagery.memory_repository import (
    InMemoryGroundImageryRequestStore,
)
from disaster_monitor.infrastructure.ground_imagery.postgres_jobs import (
    PostgresGroundImageryJobQueue,
)
from disaster_monitor.infrastructure.ground_imagery.postgres_repository import (
    PostgresGroundImageryRequestStore,
)
from disaster_monitor.infrastructure.ground_imagery.raster_artifacts import (
    RasterioCogValidator,
    RasterioStoredArtifactTileRenderer,
)
from disaster_monitor.infrastructure.ground_imagery.sentinel_hub import (
    CopernicusDataSpaceProcessRenderer,
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
from disaster_monitor.infrastructure.news.controlled_web import (
    BoundedWebFetcher,
    ControlledWebNewsFeed,
)
from disaster_monitor.infrastructure.news.feeds import (
    GdeltDocNewsFeed,
)
from disaster_monitor.infrastructure.news.web_source_registry import (
    StaticApprovedWebSourceRegistry,
)
from disaster_monitor.infrastructure.operations.filesystem_blob_store import (
    FilesystemBlobStore,
)
from disaster_monitor.infrastructure.operations.memory_provider_budget import (
    InMemoryProviderBudgetLedger,
)
from disaster_monitor.infrastructure.operations.memory_repository import (
    InMemoryOperationalRepository,
)
from disaster_monitor.infrastructure.operations.postgres_provider_budget import (
    PostgresProviderBudgetLedger,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)
from disaster_monitor.infrastructure.satellite_imagery.providers import (
    NasaGibsImageryProvider,
)
from disaster_monitor.infrastructure.source_catalog_composition import (
    build_source_catalog as build_source_catalog,
)
from disaster_monitor.infrastructure.vision.ollama_vision_adapter import (
    OllamaVisionAdapter,
)
from disaster_monitor.infrastructure.weather.composite import (
    CompositeCapWarningProvider,
)
from disaster_monitor.infrastructure.weather.meteoalarm import MeteoAlarmWarningAdapter
from disaster_monitor.infrastructure.weather.noaa_tsunami import (
    NoaaTsunamiWarningAdapter,
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
    budget_ledger = (
        PostgresProviderBudgetLedger(
            settings.operational_database_url.get_secret_value()
        )
        if settings.operational_database_url is not None
        else InMemoryProviderBudgetLedger()
    )
    return OperationalServices(
        configured_repository,
        persistence,
        OperationalEvidenceRecorder(configured_repository),
        budget_ledger,
    )


def build_breaking_news_feeds(
    settings: Settings,
    web_collection_store: WebCollectionStore | None = None,
    *,
    now: datetime | None = None,
) -> tuple[BreakingNewsFeed, ...]:
    """Build explicitly enabled public news-discovery feeds."""
    if not settings.news_sensing_enabled:
        return ()
    feeds: list[BreakingNewsFeed] = []
    if settings.gdelt_news_enabled:
        feeds.append(
            GdeltDocNewsFeed(
                timeout_seconds=settings.news_feed_timeout_seconds,
                maximum_response_bytes=settings.disaster_provider_max_response_bytes,
            )
        )
    if settings.approved_web_source_registry_path is not None:
        if web_collection_store is None:
            raise ValueError(
                "Controlled web sources require an operational state store."
            )
        registry = StaticApprovedWebSourceRegistry(
            settings.approved_web_source_registry_path
        )
        fetcher = BoundedWebFetcher(timeout_seconds=settings.news_feed_timeout_seconds)
        feeds.extend(
            ControlledWebNewsFeed(source, fetcher, web_collection_store)
            for source in registry.admitted(now=now or datetime.now(UTC))
        )
    return tuple(feeds)


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
    """Construct the public NASA GIBS map path.

    Event-scoped Copernicus Data Space products are deliberately handled by
    Ground view, where the selected product, recipe, checksum, and retention
    policy are persisted. The general map catalog has no commercial imagery
    dependency or credential-bearing tile proxy.
    """
    del settings
    return SatelliteImageryService((NasaGibsImageryProvider(),))


def build_ground_imagery_service(
    settings: Settings,
    active_incidents: ActiveIncidentsService,
    earthquake_context: EarthquakeContextService | None = None,
) -> GroundImageryService:
    """Construct the event-focused catalog, processing, and artifact workflow."""
    geometry = GeodesicGeometryEngine()
    artifact_store = FilesystemImageryArtifactStore(
        settings.ground_imagery_storage_root,
        maximum_total_bytes=settings.ground_imagery_storage_budget_bytes,
    )
    dsn = (
        settings.operational_database_url.get_secret_value()
        if settings.operational_database_url is not None
        else ""
    )
    request_store = (
        PostgresGroundImageryRequestStore(dsn)
        if dsn
        else InMemoryGroundImageryRequestStore()
    )
    client_id = (
        settings.cdse_client_id.get_secret_value()
        if settings.cdse_client_id is not None
        else None
    )
    client_secret = (
        settings.cdse_client_secret.get_secret_value()
        if settings.cdse_client_secret is not None
        else None
    )
    remote_renderer = (
        CopernicusDataSpaceProcessRenderer(
            client_id=client_id,
            client_secret=client_secret,
            process_url=settings.cdse_process_url,
            token_url=settings.cdse_token_url,
            timeout_seconds=settings.gdacs_provider_timeout_seconds,
            maximum_response_bytes=settings.ground_imagery_process_max_response_bytes,
        )
        if client_id and client_secret
        else None
    )
    local_renderer = PublicCogRenderer(
        allowed_hosts=frozenset(
            {
                "catalogue.dataspace.copernicus.eu",
                "download.dataspace.copernicus.eu",
                "eodata.dataspace.copernicus.eu",
                "stac.eodc.eu",
                "data.openaerialmap.org",
            }
        ),
        timeout_seconds=settings.gdacs_provider_timeout_seconds,
        maximum_response_bytes=settings.ground_imagery_process_max_response_bytes,
    )
    renderer = (
        FallbackGroundImageryRenderer(remote_renderer, local_renderer)
        if remote_renderer is not None
        else local_renderer
    )
    incident_context: IncidentImageryContextReader = ActiveIncidentImageryContextReader(
        active_incidents
    )
    if earthquake_context is not None:
        incident_context = EarthquakeProductImageryContextReader(
            incident_context, earthquake_context
        )
    job_queue = PostgresGroundImageryJobQueue(dsn) if dsn else None
    return GroundImageryService(
        incident_context,
        GroundImageryRegionResolver(
            geometry,
            place_lookup=GeoBoundariesPlaceLookup(
                timeout_seconds=settings.gdacs_provider_timeout_seconds,
                maximum_response_bytes=settings.country_catalog_max_response_bytes,
            ),
        ),
        CDSEStacCatalog(
            endpoint=settings.cdse_stac_url,
            timeout_seconds=settings.gdacs_provider_timeout_seconds,
            maximum_response_bytes=settings.ground_imagery_catalog_max_response_bytes,
        ),
        request_store,
        renderer=renderer,
        raster_validator=RasterioCogValidator(),
        artifact_store=artifact_store,
        tile_renderer=RasterioStoredArtifactTileRenderer(artifact_store),
        enabled=settings.ground_imagery_enabled,
        job_queue=job_queue,
    )


def build_weather_alerts_service(
    settings: Settings,
    *,
    snapshot_recorder: SourcePayloadRecorder | None = None,
) -> WeatherAlertsService:
    """Construct the separately registered authoritative warning provider."""
    providers: list[WeatherAlertProvider] = [
        NwsWeatherAlertsAdapter(
            snapshot_recorder=snapshot_recorder,
            timeout_seconds=settings.disaster_provider_timeout_seconds,
            maximum_response_bytes=settings.weather_alert_max_response_bytes,
            maximum_records=settings.weather_alert_max_records,
        )
    ]
    if settings.noaa_tsunami_warnings_enabled:
        providers.append(
            NoaaTsunamiWarningAdapter(
                snapshot_recorder=snapshot_recorder,
                timeout_seconds=settings.disaster_provider_timeout_seconds,
                maximum_response_bytes=settings.weather_alert_max_response_bytes,
                maximum_records=settings.weather_alert_max_records,
            )
        )
    if settings.meteoalarm_countries:
        providers.append(
            MeteoAlarmWarningAdapter(
                countries=settings.meteoalarm_countries,
                snapshot_recorder=snapshot_recorder,
                timeout_seconds=settings.disaster_provider_timeout_seconds,
                maximum_response_bytes=settings.weather_alert_max_response_bytes,
                maximum_records=settings.weather_alert_max_records,
            )
        )
    provider = (
        providers[0]
        if len(providers) == 1
        else CompositeCapWarningProvider(tuple(providers))
    )
    return WeatherAlertsService(provider)


def build_earthquake_context_service(settings: Settings) -> EarthquakeContextService:
    return EarthquakeContextService(
        UsgsEarthquakeProductsAdapter(
            timeout_seconds=settings.disaster_provider_timeout_seconds,
            max_response_bytes=settings.weather_alert_max_response_bytes,
        )
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


def build_investigation_resources(
    settings: Settings,
    country_catalog: StaticCountryCatalog | None = None,
    snapshot_recorder: SourcePayloadRecorder | None = None,
    operational_evidence: OperationalEvidenceRecorder | None = None,
    specialist_executor: SpecialistExecutor | None = None,
    memory_recall: MemoryRecallService | None = None,
) -> InvestigationResources:
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
    dependencies = DisasterToolDependencies(
        provider_registry=registry,
        source_catalog=source_catalog,
        event_provider=event_provider,
        situation_provider=situation_provider,
        event_policies=default_event_policy_registry(),
        evidence_reconciler=EvidenceReconciler(),
        renderer=DisasterReportRenderer(),
        clock=lambda: datetime.now(UTC),
        operational_evidence=operational_evidence,
        specialist_executor=specialist_executor,
        memory_recall=memory_recall,
    )
    return InvestigationResources(
        dependencies,
        DisasterInvestigationWorkflow(build_disaster_tool_registry(dependencies)),
        AppLifecycle(shutdown_hooks=(event_provider.aclose, situation_provider.aclose)),
    )


def build_current_disaster_report(
    settings: Settings,
    country_catalog: StaticCountryCatalog | None = None,
    snapshot_recorder: SourcePayloadRecorder | None = None,
    operational_evidence: OperationalEvidenceRecorder | None = None,
    specialist_executor: SpecialistExecutor | None = None,
    memory_recall: MemoryRecallService | None = None,
) -> CurrentDisasterReportService:
    """Compatibility builder for callers of the original report service."""
    resources = build_investigation_resources(
        settings,
        country_catalog,
        snapshot_recorder,
        operational_evidence,
        specialist_executor,
        memory_recall,
    )
    deps = resources.dependencies
    return CurrentDisasterReportService(
        deps.event_provider,
        deps.situation_provider,
        provider_registry=deps.provider_registry,
        event_policies=deps.event_policies,
        evidence_reconciler=deps.evidence_reconciler,
        renderer=deps.renderer,
        source_catalog=deps.source_catalog,
        clock=deps.clock,
        operational_evidence=deps.operational_evidence,
        specialist_executor=deps.specialist_executor,
        memory_recall=deps.memory_recall,
    )
