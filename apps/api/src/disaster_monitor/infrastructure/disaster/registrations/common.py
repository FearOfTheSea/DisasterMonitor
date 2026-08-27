"""Shared inputs and capability shapes for executable provider registration."""

from dataclasses import dataclass

from disaster_monitor.application.disaster import GeographicScope
from disaster_monitor.application.services.provider_registry import (
    ProviderCapabilities,
    ProviderRole,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.http import SourcePayloadRecorder
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)


@dataclass(frozen=True, slots=True)
class RegistrationContext:
    settings: Settings
    geography: StaticCountryCatalog
    snapshot_recorder: SourcePayloadRecorder | None


def event_capabilities(disaster: Disaster) -> ProviderCapabilities:
    scopes = frozenset({GeographicScope.COUNTRY, GeographicScope.WORLDWIDE})
    return ProviderCapabilities(
        roles=frozenset({ProviderRole.EVENT_DISCOVERY}),
        disasters=frozenset({disaster}),
        country_codes=None,
        geographic_scopes=scopes,
        event_scopes=scopes,
    )


def situation_capabilities(
    disasters: frozenset[Disaster],
    *,
    worldwide: bool,
    requires_configuration: bool = False,
) -> ProviderCapabilities:
    scopes = (
        frozenset({GeographicScope.COUNTRY, GeographicScope.WORLDWIDE})
        if worldwide
        else frozenset({GeographicScope.COUNTRY})
    )
    return ProviderCapabilities(
        roles=frozenset({ProviderRole.SITUATION_EVIDENCE}),
        disasters=disasters,
        country_codes=None,
        requires_configuration=requires_configuration,
        geographic_scopes=scopes,
        situation_scopes=scopes,
    )
