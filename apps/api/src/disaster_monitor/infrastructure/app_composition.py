"""Manual composition root for the local API."""

from datetime import UTC, datetime
from typing import cast

from disaster_monitor.application.agent.multimodal_tools import (
    MultimodalToolDependencies,
    build_multimodal_agent_tools,
)
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.ports.incident_watch_store import IncidentWatchStore
from disaster_monitor.application.ports.operator_identity import (
    TrustedOperatorIdentityPolicy,
)
from disaster_monitor.application.services.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.services.common_operational_picture import (
    CommonOperationalPictureBuilder,
)
from disaster_monitor.application.services.map_navigation import MapNavigationService
from disaster_monitor.application.services.memory_policy import MemoryPolicy
from disaster_monitor.application.services.memory_recall import MemoryRecallService
from disaster_monitor.application.services.multimodal_asset_admission import (
    MultimodalAssetAdmissionService,
)
from disaster_monitor.application.services.multimodal_association import (
    MultimodalEventAssociator,
)
from disaster_monitor.application.services.provider_freshness import (
    ProviderFreshnessService,
)
from disaster_monitor.application.services.specialist_executor import (
    SpecialistExecutor,
)
from disaster_monitor.application.services.visual_analysis import VisualAnalysisService
from disaster_monitor.application.services.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.application.source_catalog import SourceCatalogService
from disaster_monitor.application.use_cases.answer_map_question import AnswerMapQuestion
from disaster_monitor.application.use_cases.delete_conversation import (
    DeleteConversation,
)
from disaster_monitor.application.use_cases.manage_incident_watches import (
    ManageIncidentWatches,
)
from disaster_monitor.application.use_cases.record_operator_action import (
    RecordOperatorAction,
)
from disaster_monitor.application.use_cases.run_conversation_turn import (
    RunConversationTurn,
)
from disaster_monitor.application.use_cases.run_disaster_agent import RunDisasterAgent
from disaster_monitor.infrastructure.app_dependencies import (
    AppDependencies,
    AppLifecycle,
)
from disaster_monitor.infrastructure.composition_builders import (
    build_agent_model,
    build_conversation_deletion_store,
    build_conversation_repository,
    build_country_catalog,
    build_country_catalog_automation,
    build_current_disaster_report,
    build_disaster_query_parser,
    build_event_media_services,
    build_language_model,
    build_memory_repository,
    build_operational_services,
    build_satellite_imagery_service,
    build_source_catalog,
    build_specialist_model,
    build_visual_analyzer,
    build_weather_alerts_service,
)
from disaster_monitor.infrastructure.composition_models import (
    AppDependencyOverrides,
    EventMediaServices,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.media.filesystem_store import (
    FilesystemMediaAssetStore,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)


def build_app_dependencies(
    settings: Settings,
    *,
    overrides: AppDependencyOverrides | None = None,
) -> AppDependencies:
    """Construct the complete API object graph and its lifecycle delegates."""
    configured = overrides or AppDependencyOverrides()
    language_model = configured.model or build_language_model(settings)
    configured_specialist_model = (
        (configured.specialist_model or build_specialist_model(language_model))
        if settings.specialist_llm_enabled
        else None
    )
    specialist_executor = (
        SpecialistExecutor(
            configured_specialist_model,
            max_model_calls=settings.specialist_model_call_limit,
        )
        if configured_specialist_model is not None
        else None
    )
    country_catalog = build_country_catalog(settings)
    catalog_automation = (
        configured.country_catalog_automation
        or build_country_catalog_automation(settings, country_catalog)
    )
    operational = build_operational_services(
        settings, configured.operational_repository
    )
    conversations = build_conversation_repository(
        settings, configured.conversation_repository
    )
    memories = build_memory_repository(settings, configured.memory_repository)
    conversation_deletion = (
        configured.conversation_deletion_store
        if configured.conversation_deletion_store is not None
        else build_conversation_deletion_store(conversations, memories)
    )
    memory_recall = (
        MemoryRecallService(memories) if settings.long_term_memory_enabled else None
    )
    disaster_report = (
        configured.current_disaster_report
        or build_current_disaster_report(
            settings,
            country_catalog,
            snapshot_recorder=operational.snapshots.persist,
            operational_evidence=operational.evidence,
            specialist_executor=specialist_executor,
            memory_recall=memory_recall,
        )
    )
    worldwide_report = (
        configured.worldwide_disaster_report
        or WorldwideDisasterReportService(disaster_report.provider_registry)
    )
    configured_active_incidents = (
        configured.active_incidents_service
        or ActiveIncidentsService(
            disaster_report.provider_registry,
            country_event_provider=disaster_report.event_provider,
            country_catalog=country_catalog,
            event_policies=disaster_report.event_policies,
        )
    )
    query_parser = configured.disaster_query_parser or build_disaster_query_parser(
        country_catalog
    )
    source_catalog = build_source_catalog(settings)
    configured_weather_alerts = (
        configured.weather_alerts_service
        or build_weather_alerts_service(
            settings,
            snapshot_recorder=operational.snapshots.persist,
        )
    )
    configured_source_catalog = (
        configured.source_catalog_service
        or SourceCatalogService(
            source_catalog,
            disaster_report.provider_registry,
            additional_runtime_sources={
                "nws-weather-alerts": {
                    "registered": True,
                    "configured": True,
                    "provider_tier": "primary",
                    "execution_roles": ("weather_alerts",),
                }
            },
        )
    )
    configured_agent_model = (
        configured.agent_model
        if configured.agent_model is not None
        else (
            build_agent_model(settings, language_model)
            if configured.model is None
            else None
        )
    )
    configured_visual_analyzer = configured.visual_analyzer or build_visual_analyzer(
        settings
    )
    configured_satellite_imagery = (
        configured.satellite_imagery_service
        or build_satellite_imagery_service(settings)
    )

    def clock() -> datetime:
        return datetime.now(UTC)

    if configured.event_media is None:
        media_services = build_event_media_services(settings, clock=clock)
    else:
        media_services = EventMediaServices(
            configured.event_media,
            configured.media_asset_store
            or FilesystemMediaAssetStore(
                settings.event_media_blob_root,
                maximum_bytes=settings.event_media_store_maximum_bytes,
            ),
        )
    multimodal_tools = build_multimodal_agent_tools(
        MultimodalToolDependencies(
            associator=MultimodalEventAssociator(),
            visual_analysis=VisualAnalysisService(
                configured_visual_analyzer,
                clock=clock,
            ),
            cop_builder=CommonOperationalPictureBuilder(),
            clock=clock,
        )
    )
    runtime = DisasterAgentRuntime(
        country_catalog=country_catalog,
        query_parser=query_parser,
        tool_registry=disaster_report.build_agent_tools(
            source_catalog, multimodal_tools
        ),
        agent_model=configured_agent_model,
        worldwide_report=worldwide_report,
    )
    disaster_agent = RunDisasterAgent(
        runtime,
        language_model,
        MultimodalAssetAdmissionService(clock=clock),
        MapNavigationService(country_catalog),
        country_catalog,
        media_services.discovery,
        agent_model=configured_agent_model,
        diagnostics=configured.agent_diagnostics,
    )
    answer_map_question = AnswerMapQuestion(
        language_model,
        disaster_report,
        query_parser,
        disaster_agent=disaster_agent,
    )

    async def migrate_operational_repository() -> None:
        if settings.operational_auto_migrate and isinstance(
            operational.repository, PostgresOperationalRepository
        ):
            await operational.repository.migrate()

    async def close_resource(resource: object | None) -> None:
        close = getattr(resource, "aclose", None)
        if close is not None:
            await close()

    return AppDependencies(
        conversation_store=conversations,
        run_conversation_turn=RunConversationTurn(
            answer_map_question,
            conversations,
            memory_store=memories,
            memory_policy=MemoryPolicy(),
            memory_enabled=settings.long_term_memory_enabled,
        ),
        delete_conversation=DeleteConversation(conversation_deletion),
        language_model=language_model,
        active_incidents=configured_active_incidents,
        source_catalog=configured_source_catalog,
        weather_alerts=configured_weather_alerts,
        incident_watches=ManageIncidentWatches(
            cast(IncidentWatchStore, operational.repository),
            country_catalog,
        ),
        satellite_imagery=configured_satellite_imagery,
        media_assets=media_services.store,
        operational_repository=operational.repository,
        provider_freshness=ProviderFreshnessService(operational.repository),
        record_operator_action=RecordOperatorAction(operational.repository),
        operator_identity=TrustedOperatorIdentityPolicy(
            enabled=settings.trusted_operator_identity_enabled,
            header_name=settings.trusted_operator_identity_header,
        ),
        country_catalog_automation=catalog_automation,
        agent_diagnostics=configured.agent_diagnostics,
        lifecycle=AppLifecycle(
            startup_hooks=(migrate_operational_repository, catalog_automation.start),
            shutdown_hooks=(
                catalog_automation.aclose,
                lambda: close_resource(language_model),
                lambda: close_resource(disaster_report),
                lambda: close_resource(configured_agent_model),
                lambda: close_resource(configured_visual_analyzer),
                lambda: close_resource(media_services.discovery),
                configured_satellite_imagery.aclose,
                lambda: close_resource(configured_weather_alerts),
            ),
        ),
    )
