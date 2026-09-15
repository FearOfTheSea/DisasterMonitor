"""Composition policy for the maintained disaster-source catalog."""

from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)


def build_source_catalog(settings: Settings | None = None) -> StaticSourceCatalog:
    if settings is None:
        return StaticSourceCatalog()
    app_name = (settings.reliefweb_app_name or "").strip().lower()
    reliefweb_configured = bool(
        app_name
        and app_name not in {"disaster-monitor-local", "change-me", "your-app-name"}
    )
    firms_key = (
        settings.nasa_firms_map_key.get_secret_value().strip()
        if settings.nasa_firms_map_key is not None
        else ""
    )
    firms_configured = 8 <= len(firms_key) <= 200 and all(
        character.isalnum() or character in "_-" for character in firms_key
    )
    return StaticSourceCatalog(
        {
            "reliefweb-situation-reports": reliefweb_configured,
            "nasa-firms-observations": firms_configured,
            "noaa-tsunami-warnings": settings.noaa_tsunami_warnings_enabled,
            "meteoalarm-warnings": bool(settings.meteoalarm_countries),
            "hdx-hapi-context": settings.hdx_hapi_app_identifier is not None,
            "iom-dtm-displacement": bool(
                settings.iom_dtm_api_url and settings.iom_dtm_subscription_key
            ),
            "self-hosted-osrm": bool(
                settings.self_hosted_osrm_url and settings.self_hosted_osrm_data_version
            ),
        }
    )
