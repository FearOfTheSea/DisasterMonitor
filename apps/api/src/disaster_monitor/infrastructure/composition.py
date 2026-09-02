"""Stable composition-root API assembled from focused builders."""

from disaster_monitor.infrastructure.app_composition import build_app_dependencies
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
    OperationalServices,
)

__all__ = [
    "AppDependencyOverrides",
    "EventMediaServices",
    "OperationalServices",
    "build_app_dependencies",
    "build_event_media_services",
    "build_operational_services",
    "build_conversation_repository",
    "build_memory_repository",
    "build_conversation_deletion_store",
    "build_language_model",
    "build_agent_model",
    "build_specialist_model",
    "build_visual_analyzer",
    "build_satellite_imagery_service",
    "build_weather_alerts_service",
    "build_source_catalog",
    "build_country_catalog",
    "build_country_catalog_automation",
    "build_disaster_query_parser",
    "build_current_disaster_report",
]
