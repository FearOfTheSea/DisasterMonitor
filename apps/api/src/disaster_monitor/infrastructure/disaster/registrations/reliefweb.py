"""ReliefWeb executable provider registration."""

from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    situation_capabilities,
)
from disaster_monitor.infrastructure.disaster.reliefweb_adapter import (
    ReliefWebSituationAdapter,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    adapter = ReliefWebSituationAdapter(
        app_name=context.settings.reliefweb_app_name,
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        ProviderRegistration(
            "ReliefWeb",
            adapter,
            situation_capabilities(
                frozenset(Disaster),
                worldwide=False,
                requires_configuration=True,
            ),
            tier=ProviderTier.SECONDARY,
            source_id="reliefweb-situation-reports",
            configured=adapter.configured,
            allowed_hosts=adapter.allowed_hosts,
            situation_provider=adapter,
        ),
    )
