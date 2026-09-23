"""Manual composition root for the local API."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast

from disaster_monitor.application.agent.multimodal_tools import (
    MultimodalToolDependencies,
    build_multimodal_agent_tools,
)
from disaster_monitor.application.agent.runtime import DisasterAgentRuntime
from disaster_monitor.application.agent.tooling import build_disaster_tool_registry
from disaster_monitor.application.conversations.delete_conversation import (
    DeleteConversation,
)
from disaster_monitor.application.conversations.memory_policy import MemoryPolicy
from disaster_monitor.application.conversations.memory_recall import MemoryRecallService
from disaster_monitor.application.conversations.queries import ConversationQueries
from disaster_monitor.application.conversations.run_conversation_turn import (
    RunConversationTurn,
)
from disaster_monitor.application.decision.record_operator_action import (
    RecordOperatorAction,
)
from disaster_monitor.application.evidence.common_operational_picture import (
    CommonOperationalPictureBuilder,
)
from disaster_monitor.application.evidence.multimodal_asset_admission import (
    MultimodalAssetAdmissionService,
)
from disaster_monitor.application.evidence.multimodal_association import (
    MultimodalEventAssociator,
)
from disaster_monitor.application.evidence.queries import EvidenceHistoryQuery
from disaster_monitor.application.exposure.access_context import (
    RouteAccessContextService,
)
from disaster_monitor.application.field_reports.incident_verifier import (
    ProjectionIncidentVerifier,
)
from disaster_monitor.application.field_reports.media_privacy import (
    FieldMediaPrivacyService,
)
from disaster_monitor.application.field_reports.service import FieldReportService
from disaster_monitor.application.humanitarian.context import HumanitarianContextService
from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.manage_incident_watches import (
    ManageIncidentWatches,
)
from disaster_monitor.application.incidents.map_navigation import MapNavigationService
from disaster_monitor.application.ingestion.provider_freshness import (
    ProviderFreshnessService,
)
from disaster_monitor.application.ingestion.queries import QueueStatusQuery
from disaster_monitor.application.investigation.answer_map_question import (
    AnswerMapQuestion,
)
from disaster_monitor.application.investigation.run_disaster_agent import (
    RunDisasterAgent,
)
from disaster_monitor.application.investigation.specialist_executor import (
    SpecialistExecutor,
)
from disaster_monitor.application.investigation.worldwide_disaster import (
    WorldwideDisasterReportService,
)
from disaster_monitor.application.media_analysis.visual_analysis import (
    VisualAnalysisService,
)
from disaster_monitor.application.operator_workspace.service import (
    OperatorWorkspaceService,
)
from disaster_monitor.application.ports.field_reports import FieldMediaStore
from disaster_monitor.application.ports.humanitarian import (
    HumanitarianIndicatorProvider,
    OperationalPresenceProvider,
)
from disaster_monitor.application.ports.incident_projection import (
    IncidentProjectionStore,
)
from disaster_monitor.application.ports.incident_watch_store import IncidentWatchStore
from disaster_monitor.application.ports.operator_identity import (
    TrustedOperatorIdentityPolicy,
)
from disaster_monitor.application.source_catalog import SourceCatalogService
from disaster_monitor.infrastructure.app_dependencies import (
    AppDependencies,
    AppLifecycle,
)
from disaster_monitor.infrastructure.composition_builders import (
    build_agent_model,
    build_breaking_news_feeds,
    build_conversation_deletion_store,
    build_conversation_repository,
    build_country_catalog,
    build_country_catalog_automation,
    build_disaster_query_parser,
    build_earthquake_context_service,
    build_event_media_services,
    build_ground_imagery_service,
    build_investigation_resources,
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
    InvestigationResources,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.exposure.osrm import SelfHostedOsrmAdapter
from disaster_monitor.infrastructure.field_reports.filesystem_media_store import (
    FilesystemFieldMediaStore,
)
from disaster_monitor.infrastructure.field_reports.json_store import (
    JsonFieldReportStore,
)
from disaster_monitor.infrastructure.geography.static_geographic_region_catalog import (
    StaticGeographicRegionCatalog,
)
from disaster_monitor.infrastructure.humanitarian.hdx_hapi import HdxHapiContextAdapter
from disaster_monitor.infrastructure.humanitarian.iom_dtm import IomDtmContextAdapter
from disaster_monitor.infrastructure.media.filesystem_store import (
    FilesystemMediaAssetStore,
)
from disaster_monitor.infrastructure.operations.postgres_repository import (
    PostgresOperationalRepository,
)
from disaster_monitor.infrastructure.operator_workspace.json_store import (
    JsonOperatorWorkspaceStore,
)


@dataclass(frozen=True, slots=True)
class _HumanitarianFieldServices:
    humanitarian_context: HumanitarianContextService
    field_reports: FieldReportService
    field_media: FieldMediaStore
    operator_workspace: OperatorWorkspaceService
    route_access: RouteAccessContextService | None
    close_resources: tuple[object, ...]


def _build_humanitarian_field_services(
    settings: Settings,
    *,
    clock: Callable[[], datetime],
    configured: AppDependencyOverrides,
    projection_store: IncidentProjectionStore | None,
) -> _HumanitarianFieldServices:
    close_resources: list[object] = []
    humanitarian_context = configured.humanitarian_context_service
    if humanitarian_context is None:
        hdx = _build_hdx(settings, clock)
        dtm = _build_dtm(settings, clock)
        indicator_providers: tuple[HumanitarianIndicatorProvider, ...] = tuple(
            provider for provider in (hdx, dtm) if provider is not None
        )
        presence_providers: tuple[OperationalPresenceProvider, ...] = (
            (hdx,) if hdx is not None else ()
        )
        humanitarian_context = HumanitarianContextService(
            indicator_providers=indicator_providers,
            presence_providers=presence_providers,
            clock=clock,
        )
        close_resources.extend(provider for provider in (hdx, dtm) if provider)
    media_store = configured.field_media_store or FilesystemFieldMediaStore(
        settings.field_media_root,
        maximum_bytes=settings.field_media_maximum_bytes,
        clock=clock,
    )
    if configured.field_report_service is None:
        field_report_store = JsonFieldReportStore(settings.field_report_store_path)
        if configured.field_media_store is None and isinstance(
            media_store, FilesystemFieldMediaStore
        ):
            media_store.reconcile(field_report_store.referenced_media_ids())
    field_reports = configured.field_report_service or FieldReportService(
        field_report_store,
        privacy=FieldMediaPrivacyService(
            clock=clock,
            retention_days=settings.field_media_retention_days,
        ),
        media_store=media_store,
        event_verifier=(
            ProjectionIncidentVerifier(projection_store)
            if projection_store is not None
            else None
        ),
        clock=clock,
    )
    operator_workspace = (
        configured.operator_workspace_service
        or OperatorWorkspaceService(
            JsonOperatorWorkspaceStore(settings.operator_workspace_store_path),
            clock=clock,
        )
    )
    route_access = configured.route_access_service
    if route_access is None:
        osrm = _build_osrm(settings, clock)
        route_access = RouteAccessContextService(osrm) if osrm is not None else None
        if osrm is not None:
            close_resources.append(osrm)
    return _HumanitarianFieldServices(
        humanitarian_context=humanitarian_context,
        field_reports=field_reports,
        field_media=media_store,
        operator_workspace=operator_workspace,
        route_access=route_access,
        close_resources=tuple(close_resources),
    )


def _build_hdx(
    settings: Settings, clock: Callable[[], datetime]
) -> HdxHapiContextAdapter | None:
    if settings.hdx_hapi_app_identifier is None:
        return None
    return HdxHapiContextAdapter(
        app_identifier=settings.hdx_hapi_app_identifier.get_secret_value(),
        clock=clock,
    )


def _build_dtm(
    settings: Settings, clock: Callable[[], datetime]
) -> IomDtmContextAdapter | None:
    if not settings.iom_dtm_api_url or settings.iom_dtm_subscription_key is None:
        return None
    return IomDtmContextAdapter(
        api_url=settings.iom_dtm_api_url,
        subscription_key=settings.iom_dtm_subscription_key.get_secret_value(),
        clock=clock,
    )


def _build_osrm(
    settings: Settings, clock: Callable[[], datetime]
) -> SelfHostedOsrmAdapter | None:
    if not settings.self_hosted_osrm_url or not settings.self_hosted_osrm_data_version:
        return None
    return SelfHostedOsrmAdapter(
        base_url=settings.self_hosted_osrm_url,
        data_version=settings.self_hosted_osrm_data_version,
        clock=clock,
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
    legacy_report = configured.current_disaster_report
    investigation = (
        InvestigationResources(
            legacy_report.dependencies,
            legacy_report.workflow,
            AppLifecycle(shutdown_hooks=(legacy_report.aclose,)),
        )
        if legacy_report is not None
        else build_investigation_resources(
            settings,
            country_catalog,
            snapshot_recorder=operational.snapshots.persist,
            operational_evidence=operational.evidence,
            specialist_executor=specialist_executor,
            memory_recall=memory_recall,
        )
    )
    retrieval = investigation.dependencies
    configured_active_incidents = (
        configured.active_incidents_service
        or ActiveIncidentsService(
            retrieval.provider_registry,
            country_event_provider=retrieval.event_provider,
            country_catalog=country_catalog,
            geographic_region_catalog=StaticGeographicRegionCatalog(),
            event_policies=retrieval.event_policies,
            projection_store=(
                operational.repository
                if isinstance(operational.repository, PostgresOperationalRepository)
                else None
            ),
            read_from_projection=isinstance(
                operational.repository, PostgresOperationalRepository
            ),
            provider_attempt_recorder=operational.repository,
            candidate_store=operational.repository,
        )
    )
    worldwide_report = (
        configured.worldwide_disaster_report
        or WorldwideDisasterReportService(
            retrieval.provider_registry,
            incident_reader=configured_active_incidents,
        )
    )
    query_parser = configured.disaster_query_parser or build_disaster_query_parser(
        country_catalog
    )
    source_catalog = build_source_catalog(settings)
    breaking_news_feeds = build_breaking_news_feeds(settings, operational.repository)
    configured_news_ids = {feed.source_id for feed in breaking_news_feeds}
    configured_weather_alerts = (
        configured.weather_alerts_service
        or build_weather_alerts_service(
            settings,
            snapshot_recorder=operational.snapshots.persist,
        )
    )
    configured_earthquake_context = (
        configured.earthquake_context_service
        or build_earthquake_context_service(settings)
    )
    configured_source_catalog = (
        configured.source_catalog_service
        or SourceCatalogService(
            source_catalog,
            retrieval.provider_registry,
            additional_runtime_sources={
                "nws-weather-alerts": {
                    "registered": True,
                    "configured": True,
                    "provider_tier": "primary",
                    "execution_roles": ("weather_alerts",),
                },
                "noaa-tsunami-warnings": {
                    "registered": True,
                    "configured": settings.noaa_tsunami_warnings_enabled,
                    "provider_tier": "primary",
                    "execution_roles": ("weather_alerts",),
                },
                "meteoalarm-warnings": {
                    "registered": True,
                    "configured": bool(settings.meteoalarm_countries),
                    "provider_tier": "primary",
                    "execution_roles": ("weather_alerts",),
                },
                "hdx-hapi-context": {
                    "registered": True,
                    "configured": settings.hdx_hapi_app_identifier is not None,
                    "provider_tier": "secondary",
                    "execution_roles": ("humanitarian_context",),
                },
                "iom-dtm-displacement": {
                    "registered": True,
                    "configured": bool(
                        settings.iom_dtm_api_url and settings.iom_dtm_subscription_key
                    ),
                    "provider_tier": "secondary",
                    "execution_roles": ("humanitarian_context",),
                },
                "self-hosted-osrm": {
                    "registered": True,
                    "configured": bool(
                        settings.self_hosted_osrm_url
                        and settings.self_hosted_osrm_data_version
                    ),
                    "provider_tier": "secondary",
                    "execution_roles": ("route_context",),
                },
                **{
                    source_id: {
                        "registered": True,
                        "configured": source_id in configured_news_ids,
                        "provider_tier": "secondary",
                        "execution_roles": ("breaking_news_discovery",),
                    }
                    for source_id in ("gdelt-news",)
                },
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
    configured_ground_imagery = (
        configured.ground_imagery_service
        or build_ground_imagery_service(
            settings,
            configured_active_incidents,
            configured_earthquake_context,
        )
    )

    def clock() -> datetime:
        return datetime.now(UTC)

    humanitarian_field = _build_humanitarian_field_services(
        settings,
        clock=clock,
        configured=configured,
        projection_store=(
            operational.repository
            if isinstance(operational.repository, PostgresOperationalRepository)
            else None
        ),
    )

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
        tool_registry=build_disaster_tool_registry(
            replace(retrieval, source_catalog=source_catalog), multimodal_tools
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
        investigation.workflow,
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

    async def close_humanitarian_field_resources() -> None:
        for resource in humanitarian_field.close_resources:
            await close_resource(resource)

    return AppDependencies(
        conversation_queries=ConversationQueries(conversations),
        evidence_history=EvidenceHistoryQuery(operational.repository),
        queue_status=QueueStatusQuery(operational.repository),
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
        earthquake_context=configured_earthquake_context,
        humanitarian_context=humanitarian_field.humanitarian_context,
        field_reports=humanitarian_field.field_reports,
        field_media=humanitarian_field.field_media,
        operator_workspace=humanitarian_field.operator_workspace,
        incident_watches=ManageIncidentWatches(
            cast(IncidentWatchStore, operational.repository),
            country_catalog,
        ),
        satellite_imagery=configured_satellite_imagery,
        ground_imagery=configured_ground_imagery,
        media_assets=media_services.store,
        operational_repository=operational.repository,
        provider_freshness=ProviderFreshnessService(
            operational.repository,
            source_ids=tuple(
                registration.source_id
                for registration in retrieval.provider_registry.registrations
                if registration.source_id is not None
            ),
            unconfigured_source_ids=tuple(
                registration.source_id
                for registration in retrieval.provider_registry.registrations
                if registration.source_id is not None and not registration.configured
            ),
        ),
        record_operator_action=RecordOperatorAction(operational.repository),
        operator_identity=TrustedOperatorIdentityPolicy(
            enabled=settings.trusted_operator_identity_enabled,
            header_name=settings.trusted_operator_identity_header,
        ),
        country_catalog_automation=catalog_automation,
        agent_diagnostics=configured.agent_diagnostics,
        provider_budget=operational.provider_budget,
        route_access=humanitarian_field.route_access,
        lifecycle=AppLifecycle(
            startup_hooks=(migrate_operational_repository, catalog_automation.start),
            shutdown_hooks=(
                catalog_automation.aclose,
                lambda: close_resource(language_model),
                investigation.lifecycle.shutdown,
                lambda: close_resource(configured_agent_model),
                lambda: close_resource(configured_visual_analyzer),
                lambda: close_resource(media_services.discovery),
                configured_satellite_imagery.aclose,
                configured_ground_imagery.aclose,
                lambda: close_resource(configured_weather_alerts),
                configured_earthquake_context.aclose,
                close_humanitarian_field_resources,
            ),
        ),
    )
