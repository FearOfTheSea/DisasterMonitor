"""Registration of event-linked GDACS observed-impact retrieval."""

from disaster_monitor.application.sources.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.gdacs_situation_adapter import (
    GdacsSituationAdapter,
)
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    situation_capabilities,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    adapter = GdacsSituationAdapter(
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.gdacs_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        ProviderRegistration(
            adapter.provider_name,
            adapter,
            situation_capabilities(
                frozenset(
                    {
                        Disaster.EARTHQUAKE,
                        Disaster.FLOOD,
                        Disaster.WILDFIRE,
                        Disaster.TROPICAL_CYCLONE,
                        Disaster.VOLCANIC_ERUPTION,
                    }
                ),
                worldwide=False,
            ),
            tier=ProviderTier.SECONDARY,
            source_id=adapter.source_id,
            allowed_hosts=adapter.allowed_hosts,
            situation_provider=adapter,
            event_eligibility=adapter.supports_event,
        ),
    )
