"""Manual composition root for the local API."""

from dataclasses import dataclass

from disaster_monitor.application.agent.diagnostics import AgentDiagnostics
from disaster_monitor.application.ports.agent_model import AgentModel
from disaster_monitor.application.ports.conversation_deletion import (
    ConversationDeletionStore,
)
from disaster_monitor.application.ports.conversation_store import ConversationStore
from disaster_monitor.application.ports.event_media import (
    EventMediaDiscovery,
    MediaAssetStore,
)
from disaster_monitor.application.ports.geography import CountryCatalogUpdateAutomation
from disaster_monitor.application.ports.language_model import LanguageModel
from disaster_monitor.application.ports.memory_store import MemoryStore
from disaster_monitor.application.ports.operational_state import OperationalRepository
from disaster_monitor.application.ports.specialist_model import SpecialistModel
from disaster_monitor.application.ports.visual_analysis import VisualAnalyzer
from disaster_monitor.application.satellite_imagery import SatelliteImageryService
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.services.current_disaster_report import (
    CurrentDisasterReportService,
)
from disaster_monitor.application.services.disaster_query_parser import (
    DisasterQueryParser,
)
from disaster_monitor.application.services.operational_evidence import (
    OperationalEvidenceRecorder,
)
from disaster_monitor.application.services.operational_ingestion import (
    SnapshotPersistenceService,
)
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.application.source_catalog import SourceCatalogService
from disaster_monitor.application.weather_alerts import WeatherAlertsService


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


@dataclass(frozen=True, slots=True)
class AppDependencyOverrides:
    """Typed test and embedding overrides for the application object graph."""

    model: LanguageModel | None = None
    current_disaster_report: CurrentDisasterReportService | None = None
    disaster_query_parser: DisasterQueryParser | None = None
    agent_model: AgentModel | None = None
    visual_analyzer: VisualAnalyzer | None = None
    operational_repository: OperationalRepository | None = None
    country_catalog_automation: CountryCatalogUpdateAutomation | None = None
    worldwide_disaster_report: WorldwideDisasterReportService | None = None
    event_media: EventMediaDiscovery | None = None
    media_asset_store: MediaAssetStore | None = None
    active_incidents_service: ActiveIncidentsService | None = None
    conversation_repository: ConversationStore | None = None
    satellite_imagery_service: SatelliteImageryService | None = None
    source_catalog_service: SourceCatalogService | None = None
    weather_alerts_service: WeatherAlertsService | None = None
    specialist_model: SpecialistModel | None = None
    memory_repository: MemoryStore | None = None
    conversation_deletion_store: ConversationDeletionStore | None = None
    agent_diagnostics: AgentDiagnostics | None = None
