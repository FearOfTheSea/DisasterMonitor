"""Aggregate executable provider-family registrations for composition."""

from disaster_monitor.application.services.provider_registry import ProviderRegistration
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.http import SourcePayloadRecorder
from disaster_monitor.infrastructure.disaster.registrations import (
    copernicus_ems_mapping,
)
from disaster_monitor.infrastructure.disaster.registrations.cems_gfm import (
    build as build_cems_gfm,
)
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
)
from disaster_monitor.infrastructure.disaster.registrations.emsc import (
    build as build_emsc,
)
from disaster_monitor.infrastructure.disaster.registrations.gdacs import (
    build as build_gdacs,
)
from disaster_monitor.infrastructure.disaster.registrations.ibtracs import (
    build as build_ibtracs,
)
from disaster_monitor.infrastructure.disaster.registrations.nasa_coolr import (
    build as build_nasa_coolr,
)
from disaster_monitor.infrastructure.disaster.registrations.nasa_eonet import (
    build as build_nasa_eonet,
)
from disaster_monitor.infrastructure.disaster.registrations.nasa_firms import (
    build as build_nasa_firms,
)
from disaster_monitor.infrastructure.disaster.registrations.reliefweb import (
    build as build_reliefweb,
)
from disaster_monitor.infrastructure.disaster.registrations.smithsonian_gvp import (
    build as build_smithsonian_gvp,
)
from disaster_monitor.infrastructure.disaster.registrations.usgs import (
    build as build_usgs,
)
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


def build_provider_registrations(
    settings: Settings,
    geography: StaticCountryCatalog,
    snapshot_recorder: SourcePayloadRecorder | None,
) -> tuple[ProviderRegistration, ...]:
    """Build the governed executable registry without consulting the source catalog."""
    context = RegistrationContext(settings, geography, snapshot_recorder)
    gdacs = build_gdacs(context)
    return (
        *build_cems_gfm(context),
        gdacs[0],
        *build_emsc(context),
        *build_usgs(context),
        *build_nasa_eonet(context),
        gdacs[1],
        *build_nasa_firms(context),
        *build_nasa_coolr(context),
        *copernicus_ems_mapping.build(context),
        gdacs[2],
        *build_ibtracs(context),
        *build_smithsonian_gvp(context),
        gdacs[3],
        *build_reliefweb(context),
    )


__all__ = ["build_provider_registrations"]
