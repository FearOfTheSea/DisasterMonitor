"""Bounded provider-neutral union of authoritative CAP warning feeds."""

from datetime import datetime

from disaster_monitor.application.ports.weather_alerts import (
    WeatherAlertBatch,
    WeatherAlertProvider,
    WeatherAlertProviderIssue,
)
from disaster_monitor.domain.warnings import CapAlert


class CompositeCapWarningProvider:
    source_id = "official-cap-warnings"
    publisher = "Configured official CAP warning authorities"
    geographic_scope = "Configured authority jurisdictions; coverage is not global"
    limitations = (
        "Each warning retains its issuer and source-specific limitations.",
        "A warning is not a physical-incident observation.",
    )

    def __init__(self, providers: tuple[WeatherAlertProvider, ...]) -> None:
        if not providers:
            raise ValueError("A warning composite requires at least one provider.")
        self._providers = providers

    async def fetch_active_alerts(self, *, now: datetime) -> WeatherAlertBatch:
        alerts: list[CapAlert] = []
        issues: list[WeatherAlertProviderIssue] = []
        for provider in self._providers:
            batch = await provider.fetch_active_alerts(now=now)
            alerts.extend(batch.alerts)
            if batch.issue is not None:
                issues.append(batch.issue)
        alerts.sort(
            key=lambda item: (item.sent, item.sender, item.identifier), reverse=True
        )
        issue = None
        if issues:
            issue = WeatherAlertProviderIssue(
                reason_code="warning_sources_degraded",
                detail="; ".join(item.detail for item in issues),
                retryable=any(item.retryable for item in issues),
                partial=bool(alerts) or any(item.partial for item in issues),
            )
        return WeatherAlertBatch(tuple(alerts), issue)

    async def aclose(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
