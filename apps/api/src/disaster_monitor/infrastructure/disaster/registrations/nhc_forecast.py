"""NOAA NHC/CPHC cyclone forecast registration."""

from disaster_monitor.application.services.provider_registry import (
    ProviderRegistration,
    ProviderTier,
)
from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.infrastructure.disaster.nhc_forecast_adapter import (
    NhcCycloneForecastAdapter,
)
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
    situation_capabilities,
)


def build(context: RegistrationContext) -> tuple[ProviderRegistration, ...]:
    adapter = NhcCycloneForecastAdapter(
        snapshot_recorder=context.snapshot_recorder,
        timeout_seconds=context.settings.disaster_provider_timeout_seconds,
        max_response_bytes=context.settings.disaster_provider_max_response_bytes,
    )
    return (
        ProviderRegistration(
            "NOAA NHC/CPHC cyclone forecasts",
            adapter,
            situation_capabilities(
                frozenset({Disaster.TROPICAL_CYCLONE}), worldwide=True
            ),
            tier=ProviderTier.PRIMARY,
            source_id="noaa-nhc-cyclone-forecast",
            allowed_hosts=adapter.allowed_hosts,
            situation_provider=adapter,
            worldwide_situation_provider=adapter,
        ),
    )
