"""USGS executable provider registration."""

from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    event_capabilities,
)
from disaster_monitor.infrastructure.disaster.usgs_adapter import UsgsEarthquakeAdapter


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    adapter = UsgsEarthquakeAdapter(
        geography=context.geography,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        ProviderRegistration(
            "USGS",
            adapter,
            event_capabilities(Disaster.EARTHQUAKE),
            tier=ProviderTier.SECONDARY,
            source_id="usgs-earthquakes",
            allowed_hosts=adapter.allowed_hosts,
            event_provider=adapter,
            worldwide_provider=adapter,
        ),
    )
