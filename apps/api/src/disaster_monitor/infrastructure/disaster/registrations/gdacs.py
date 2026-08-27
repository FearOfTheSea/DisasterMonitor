"""GDACS executable provider-family registrations."""

from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.gdacs_adapter import (
    GdacsFloodAdapter,
    GdacsTropicalCycloneAdapter,
    GdacsVolcanicEruptionAdapter,
    GdacsWildfireAdapter,
)
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    event_capabilities,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    floods = GdacsFloodAdapter(
        geography=context.geography,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    cyclones = GdacsTropicalCycloneAdapter(
        geography=context.geography,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    wildfires = GdacsWildfireAdapter(
        geography=context.geography,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    volcanoes = GdacsVolcanicEruptionAdapter(
        geography=context.geography,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        _registration("GDACS floods", floods, Disaster.FLOOD, "gdacs-floods"),
        _registration(
            "GDACS wildfires",
            wildfires,
            Disaster.WILDFIRE,
            "gdacs-wildfires",
        ),
        _registration(
            "GDACS tropical cyclones",
            cyclones,
            Disaster.TROPICAL_CYCLONE,
            "gdacs-tropical-cyclones",
        ),
        _registration(
            "GDACS volcanic eruptions",
            volcanoes,
            Disaster.VOLCANIC_ERUPTION,
            "gdacs-volcanic-eruptions",
        ),
    )


def _registration(
    name: str,
    adapter: GdacsFloodAdapter
    | GdacsWildfireAdapter
    | GdacsTropicalCycloneAdapter
    | GdacsVolcanicEruptionAdapter,
    disaster: Disaster,
    source_id: str,
) -> ProviderRegistration:
    return ProviderRegistration(
        name,
        adapter,
        event_capabilities(disaster),
        tier=ProviderTier.SECONDARY,
        source_id=source_id,
        allowed_hosts=adapter.allowed_hosts,
        event_provider=adapter,
        worldwide_provider=adapter,
    )
