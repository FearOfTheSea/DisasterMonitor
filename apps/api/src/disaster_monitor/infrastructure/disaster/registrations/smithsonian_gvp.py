"""Smithsonian GVP executable provider registration."""

from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    event_capabilities,
)
from disaster_monitor.infrastructure.disaster.smithsonian_gvp_adapter import (
    SmithsonianGvpAdapter,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    adapter = SmithsonianGvpAdapter(
        geography=context.geography,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        ProviderRegistration(
            "Smithsonian / USGS Weekly Volcanic Activity Report",
            adapter,
            event_capabilities(Disaster.VOLCANIC_ERUPTION),
            tier=ProviderTier.PRIMARY,
            source_id="smithsonian-usgs-volcanic-activity",
            allowed_hosts=adapter.allowed_hosts,
            event_provider=adapter,
            worldwide_provider=adapter,
        ),
    )
