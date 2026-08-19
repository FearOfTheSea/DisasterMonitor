"""Manual composition root for the local API."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from disaster_monitor.application.disaster import GeographicScope
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.event_media import (
    EventMediaDiscovery,
    MediaAssetStore,
)
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
from disaster_monitor.application.services.event_media import DisasterMediaService
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
    ProviderTier,
)
from disaster_monitor.application.services.source_consistency import (
    validate_provider_source_consistency,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.cems_gfm_adapter import CemsGfmAdapter
from disaster_monitor.infrastructure.disaster.composite import (
    CompositeDisasterEventProvider,
    CompositeSituationReportProvider,
)
from disaster_monitor.infrastructure.disaster.gdacs_adapter import (
    GdacsTropicalCycloneAdapter,
)
from disaster_monitor.infrastructure.disaster.http import SourcePayloadRecorder
from disaster_monitor.infrastructure.disaster.nasa_coolr_adapter import (
    NasaCoolrLandslideAdapter,
)
from disaster_monitor.infrastructure.disaster.nasa_eonet_adapter import (
    NasaEonetWildfireAdapter,
)
from disaster_monitor.infrastructure.disaster.reliefweb_adapter import (
    ReliefWebSituationAdapter,
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
from disaster_monitor.infrastructure.media.memory_store import InMemoryMediaAssetStore
from disaster_monitor.infrastructure.media.news_scraper import NewsEventMediaProvider
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


@dataclass(frozen=True, slots=True)
class EventMediaServices:
    discovery: EventMediaDiscovery | None
    store: MediaAssetStore


def build_event_media_services(
    settings: Settings, *, clock: Callable[[], datetime]
) -> EventMediaServices:
    store = InMemoryMediaAssetStore(
        maximum_bytes=settings.event_media_store_maximum_bytes
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
    """Construct the packaged maintained global disaster-source catalog."""
    if settings is None:
        return StaticSourceCatalog()
    app_name = (settings.reliefweb_app_name or "").strip().lower()
    configured = bool(
        app_name
        and app_name not in {"disaster-monitor-local", "change-me", "your-app-name"}
    )
    return StaticSourceCatalog({"reliefweb-situation-reports": configured})


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
) -> CurrentDisasterReportService:
    """Construct capability-registered live disaster providers."""
    geography = country_catalog or build_country_catalog()
    usgs = UsgsEarthquakeAdapter(
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
    coolr = NasaCoolrLandslideAdapter(
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
