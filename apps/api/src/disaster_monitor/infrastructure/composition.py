"""Manual composition root for the local API."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from disaster_monitor.application.disaster import GeographicScope
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.conversation_deletion import (
    ConversationDeletionStore,
)
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.ports.event_media import (
    EventMediaDiscovery,
    MediaAssetStore,
)
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
    ProviderCapabilities,
    ProviderRegistration,
    ProviderRegistry,
    ProviderRole,
    ProviderTier,
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
from disaster_monitor.domain.disaster import Disaster
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
from disaster_monitor.infrastructure.disaster.cems_gfm_adapter import CemsGfmAdapter
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
    CompositeSituationReportProvider,
)
from disaster_monitor.infrastructure.disaster.copernicus_ems_mapping_adapter import (
    CopernicusRapidMappingAdapter,
)
from disaster_monitor.infrastructure.disaster.emsc_adapter import (
    EmscEarthquakeAdapter,
)
from disaster_monitor.infrastructure.disaster.gdacs_adapter import (
    GdacsFloodAdapter,
    GdacsTropicalCycloneAdapter,
    GdacsVolcanicEruptionAdapter,
    GdacsWildfireAdapter,
)
from disaster_monitor.infrastructure.disaster.http import SourcePayloadRecorder
from disaster_monitor.infrastructure.disaster.ibtracs_adapter import IbtracsTrackAdapter
from disaster_monitor.infrastructure.disaster.nasa_coolr_adapter import (
    NasaCoolrLandslideAdapter,
)
from disaster_monitor.infrastructure.disaster.nasa_eonet_adapter import (
    NasaEonetWildfireAdapter,
)
from disaster_monitor.infrastructure.disaster.nasa_firms_adapter import (
    NasaFirmsObservationAdapter,
)
from disaster_monitor.infrastructure.disaster.reliefweb_adapter import (
    ReliefWebSituationAdapter,
)
from disaster_monitor.infrastructure.disaster.smithsonian_gvp_adapter import (
    SmithsonianGvpAdapter,
)
from disaster_monitor.infrastructure.disaster.usgs_adapter import UsgsEarthquakeAdapter
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


@dataclass(frozen=True, slots=True)
class OperationalServices:
    """Explicit operational persistence dependencies for API composition."""

    repository: OperationalRepository
    snapshots: SnapshotPersistenceService
    evidence: OperationalEvidenceRecorder


@dataclass(frozen=True, slots=True)
class EventMediaServices:
    discovery: EventMediaDiscovery | None
    store: MediaAssetStore


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
    return StructuredAgentModel(language_model or build_language_model(settings))


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
    usgs = UsgsEarthquakeAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    emsc = EmscEarthquakeAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    gdacs = GdacsTropicalCycloneAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    ibtracs = IbtracsTrackAdapter(
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    gdacs_floods = GdacsFloodAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    gdacs_wildfires = GdacsWildfireAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    gdacs_volcanoes = GdacsVolcanicEruptionAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    gfm = CemsGfmAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    eonet = NasaEonetWildfireAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    firms = NasaFirmsObservationAdapter(
        map_key=settings.nasa_firms_map_key,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    coolr = NasaCoolrLandslideAdapter(
        geography=geography,
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    copernicus_mapping = CopernicusRapidMappingAdapter(
        snapshot_recorder=snapshot_recorder,
        timeout_seconds=settings.disaster_provider_timeout_seconds,
        max_response_bytes=settings.disaster_provider_max_response_bytes,
    )
    smithsonian_gvp = SmithsonianGvpAdapter(
        geography=geography,
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
    registry = ProviderRegistry(
        (
            ProviderRegistration(
                "CEMS Global Flood Monitoring (GFM)",
                gfm,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.FLOOD}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.PRIMARY,
                source_id="cems-gfm-floods",
                allowed_hosts=gfm.allowed_hosts,
                event_provider=gfm,
                worldwide_provider=gfm,
            ),
            ProviderRegistration(
                "GDACS floods",
                gdacs_floods,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.FLOOD}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="gdacs-floods",
                allowed_hosts=gdacs_floods.allowed_hosts,
                event_provider=gdacs_floods,
                worldwide_provider=gdacs_floods,
            ),
            ProviderRegistration(
                "EMSC SeismicPortal",
                emsc,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.EARTHQUAKE}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="emsc-earthquakes",
                allowed_hosts=emsc.allowed_hosts,
                event_provider=emsc,
                worldwide_provider=emsc,
            ),
            ProviderRegistration(
                "USGS",
                usgs,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.EARTHQUAKE}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="usgs-earthquakes",
                allowed_hosts=usgs.allowed_hosts,
                event_provider=usgs,
                worldwide_provider=usgs,
            ),
            ProviderRegistration(
                "NASA EONET Wildfires",
                eonet,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.WILDFIRE}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.PRIMARY,
                source_id="nasa-eonet-wildfires",
                allowed_hosts=eonet.allowed_hosts,
                event_provider=eonet,
                worldwide_provider=eonet,
            ),
            ProviderRegistration(
                "GDACS wildfires",
                gdacs_wildfires,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.WILDFIRE}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="gdacs-wildfires",
                allowed_hosts=gdacs_wildfires.allowed_hosts,
                event_provider=gdacs_wildfires,
                worldwide_provider=gdacs_wildfires,
            ),
            ProviderRegistration(
                "NASA FIRMS observations",
                firms,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    disasters=frozenset({Disaster.WILDFIRE}),
                    country_codes=None,
                    requires_configuration=True,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    situation_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="nasa-firms-observations",
                configured=firms.configured,
                allowed_hosts=firms.allowed_hosts,
                situation_provider=firms,
                worldwide_situation_provider=firms,
            ),
            ProviderRegistration(
                "NASA COOLR Landslides",
                coolr,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.LANDSLIDE}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.PRIMARY,
                source_id="nasa-coolr-landslides",
                allowed_hosts=coolr.allowed_hosts,
                event_provider=coolr,
                worldwide_provider=coolr,
            ),
            ProviderRegistration(
                "Copernicus EMS Rapid Mapping landslides",
                copernicus_mapping,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    disasters=frozenset({Disaster.LANDSLIDE}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    situation_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="copernicus-rapid-mapping-landslides",
                allowed_hosts=copernicus_mapping.allowed_hosts,
                situation_provider=copernicus_mapping,
                worldwide_situation_provider=copernicus_mapping,
            ),
            ProviderRegistration(
                "GDACS tropical cyclones",
                gdacs,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.TROPICAL_CYCLONE}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="gdacs-tropical-cyclones",
                allowed_hosts=gdacs.allowed_hosts,
                event_provider=gdacs,
                worldwide_provider=gdacs,
            ),
            ProviderRegistration(
                "NOAA IBTrACS track reconciliation",
                ibtracs,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    disasters=frozenset({Disaster.TROPICAL_CYCLONE}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    situation_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="noaa-ibtracs-tracks",
                allowed_hosts=ibtracs.allowed_hosts,
                situation_provider=ibtracs,
                worldwide_situation_provider=ibtracs,
            ),
            ProviderRegistration(
                "Smithsonian / USGS Weekly Volcanic Activity Report",
                smithsonian_gvp,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.VOLCANIC_ERUPTION}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.PRIMARY,
                source_id="smithsonian-usgs-volcanic-activity",
                allowed_hosts=smithsonian_gvp.allowed_hosts,
                event_provider=smithsonian_gvp,
                worldwide_provider=smithsonian_gvp,
            ),
            ProviderRegistration(
                "GDACS volcanic eruptions",
                gdacs_volcanoes,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
                    disasters=frozenset({Disaster.VOLCANIC_ERUPTION}),
                    country_codes=None,
                    geographic_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                    event_scopes=frozenset(
                        {GeographicScope.COUNTRY, GeographicScope.WORLDWIDE}
                    ),
                ),
                tier=ProviderTier.SECONDARY,
                source_id="gdacs-volcanic-eruptions",
                allowed_hosts=gdacs_volcanoes.allowed_hosts,
                event_provider=gdacs_volcanoes,
                worldwide_provider=gdacs_volcanoes,
            ),
            ProviderRegistration(
                "ReliefWeb",
                reliefweb,
                ProviderCapabilities(
                    roles=frozenset({ProviderRole.SITUATION_EVIDENCE}),
                    disasters=frozenset(Disaster),
                    country_codes=None,
                    geographic_scopes=frozenset({GeographicScope.COUNTRY}),
                    requires_configuration=True,
                ),
                tier=ProviderTier.SECONDARY,
                source_id="reliefweb-situation-reports",
                configured=reliefweb.configured,
                allowed_hosts=reliefweb.allowed_hosts,
                situation_provider=reliefweb,
            ),
        )
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
