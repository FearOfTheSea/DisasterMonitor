"""Copernicus EMS Mapping executable provider registration."""

from disaster_monitor.application.sources.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.copernicus_ems_mapping_adapter import (
    CopernicusRapidMappingAdapter,
)
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    situation_capabilities,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    return tuple(_registration(context, disaster) for disaster in Disaster)


def _registration(
    context: RegistrationContext, disaster: Disaster
) -> ProviderRegistration:
    adapter = CopernicusRapidMappingAdapter(
        disaster=disaster,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return ProviderRegistration(
        adapter.provider_name,
        adapter,
        situation_capabilities(frozenset({disaster}), worldwide=True),
        tier=ProviderTier.SECONDARY,
        source_id=adapter.source_id,
        allowed_hosts=adapter.allowed_hosts,
        situation_provider=adapter,
        worldwide_situation_provider=adapter,
    )
