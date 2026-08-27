"""EMSC executable provider registration."""

from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.emsc_adapter import EmscEarthquakeAdapter
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    event_capabilities,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    adapter = EmscEarthquakeAdapter(
        geography=context.geography,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        ProviderRegistration(
            "EMSC SeismicPortal",
            adapter,
            event_capabilities(Disaster.EARTHQUAKE),
            tier=ProviderTier.SECONDARY,
            source_id="emsc-earthquakes",
            allowed_hosts=adapter.allowed_hosts,
            event_provider=adapter,
            worldwide_provider=adapter,
        ),
    )
