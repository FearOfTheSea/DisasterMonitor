from dataclasses import replace

from disaster_monitor.application.agent.models import SourceInformationRole
from disaster_monitor.application.source_catalog import SourceCatalogService
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.infrastructure.composition import (
    build_current_disaster_report,
    build_source_catalog,
)
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.sources.static_source_catalog import (
    StaticSourceCatalog,
)


def test_packaged_source_catalog_has_only_implemented_sources() -> None:
    catalog = StaticSourceCatalog()

    assert {item.source_id for item in catalog.sources()} == {
        "cems-gfm-floods",
        "copernicus-effis-gwis",
        "copernicus-glofas-forecast",
        "copernicus-global-drought-observatory",
        "copernicus-rapid-mapping-earthquakes",
        "copernicus-rapid-mapping-floods",
        "copernicus-rapid-mapping-landslides",
        "copernicus-rapid-mapping-tropical-cyclones",
        "copernicus-rapid-mapping-volcanic-eruptions",
        "copernicus-rapid-mapping-wildfires",
        "emsc-earthquakes",
        "gdacs-earthquakes",
        "gdacs-floods",
        "gdacs-situation-reports",
        "gdacs-tropical-cyclones",
        "gdacs-volcanic-eruptions",
        "gdacs-wildfires",
        "gdelt-news",
        "ghsl-population",
        "hdx-hapi-context",
        "inform-risk",
        "iom-dtm-displacement",
        "meteoalarm-warnings",
        "nasa-coolr-landslides",
        "nasa-eonet-wildfires",
        "nasa-firms-observations",
        "noaa-ibtracs-tracks",
        "noaa-nhc-cyclone-forecast",
        "noaa-tsunami-warnings",
        "nws-weather-alerts",
        "openaerialmap-imagery",
        "openstreetmap-geofabrik",
        "reliefweb-situation-reports",
        "self-hosted-osrm",
        "smithsonian-usgs-volcanic-activity",
        "usgs-aftershock-forecast",
        "usgs-earthquakes",
        "usgs-ground-failure",
        "usgs-pager",
        "usgs-shakemap",
        "worldpop-population",
    }
    assert all(
        source.implementation_status.startswith("implemented")
        for source in catalog.sources()
    )
    imagery_sources = {
        source.source_id
        for source in catalog.sources()
        if SourceInformationRole.IMAGERY in source.information_roles
    }
    assert imagery_sources == {"openaerialmap-imagery"}


def test_catalog_projection_keeps_maintained_metadata_and_runtime_state_separate() -> (
    None
):
    settings = Settings(
        _env_file=None,
        reliefweb_app_name=None,
        nasa_firms_map_key=None,
    )
    catalog = build_source_catalog(settings)
    report = build_current_disaster_report(settings, StaticCountryCatalog())
    service = SourceCatalogService(
        catalog,
        report.provider_registry,
        additional_runtime_sources={
            "nws-weather-alerts": {
                "registered": True,
                "configured": True,
                "provider_tier": "primary",
                "execution_roles": ("weather_alerts",),
            }
        },
    )

    snapshot = service.read()
    by_id = {source.source_id: source for source in snapshot.sources}

    assert snapshot.catalog_version == catalog.version
    assert by_id["usgs-earthquakes"].publisher == "United States Geological Survey"
    assert by_id["usgs-earthquakes"].operational_state.registered is True
    assert by_id["usgs-earthquakes"].operational_state.provider_tier == "secondary"
    assert by_id["reliefweb-situation-reports"].operational_state.configured is False
    assert by_id["nws-weather-alerts"].information_roles == ("official_warning",)
    assert by_id["nws-weather-alerts"].supported_disasters == ()
    assert by_id["nws-weather-alerts"].operational_state.execution_roles == (
        "weather_alerts",
    )
    assert by_id["nws-weather-alerts"].documentation_path.endswith(
        "noaa-nws-weather-alerts.md"
    )
    assert all(source.stale_threshold_seconds is None for source in snapshot.sources)


def test_catalog_read_does_not_turn_catalog_entries_into_registrations() -> None:
    catalog = build_source_catalog(Settings(_env_file=None))
    report = build_current_disaster_report(
        Settings(_env_file=None), StaticCountryCatalog()
    )
    registration_ids = {
        registration.source_id
        for registration in report.provider_registry.registrations
    }

    assert "nws-weather-alerts" in {source.source_id for source in catalog.sources()}
    assert "nws-weather-alerts" not in registration_ids

    detached = replace(
        catalog.get("nws-weather-alerts"),  # type: ignore[arg-type]
        provider_registration_name="Not a disaster provider",
    )
    assert detached.source_id == "nws-weather-alerts"
    assert isinstance(report.provider_registry, ProviderRegistry)
