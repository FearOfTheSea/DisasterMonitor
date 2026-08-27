"""NASA FIRMS executable provider registration."""

from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.nasa_firms_adapter import (
    NasaFirmsObservationAdapter,
)
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    situation_capabilities,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    adapter = NasaFirmsObservationAdapter(
        map_key=context.settings.nasa_firms_map_key,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        ProviderRegistration(
            "NASA FIRMS observations",
            adapter,
            situation_capabilities(
                frozenset({Disaster.WILDFIRE}),
                worldwide=True,
                requires_configuration=True,
            ),
            tier=ProviderTier.SECONDARY,
            source_id="nasa-firms-observations",
            configured=adapter.configured,
            allowed_hosts=adapter.allowed_hosts,
            situation_provider=adapter,
            worldwide_situation_provider=adapter,
        ),
    )
