"""CEMS GFM executable provider registration."""

from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.cems_gfm_adapter import CemsGfmAdapter
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    event_capabilities,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    adapter = CemsGfmAdapter(
        geography=context.geography,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        ProviderRegistration(
            "CEMS Global Flood Monitoring (GFM)",
            adapter,
            event_capabilities(Disaster.FLOOD),
            tier=ProviderTier.PRIMARY,
            source_id="cems-gfm-floods",
            allowed_hosts=adapter.allowed_hosts,
            event_provider=adapter,
            worldwide_provider=adapter,
        ),
    )
