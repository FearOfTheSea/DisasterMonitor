"""Application port for bounded authoritative weather-alert retrieval."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from disaster_monitor.application.weather_alerts import WeatherAlert


@dataclass(frozen=True, slots=True)
class WeatherAlertProviderIssue:
    """One typed provider limitation without leaking transport details."""

    reason_code: str
    detail: str
    retryable: bool = False
    partial: bool = False


@dataclass(frozen=True, slots=True)
class WeatherAlertBatch:
    """Provider result that keeps successful-empty distinct from failure."""

    alerts: tuple[WeatherAlert, ...] = ()
    issue: WeatherAlertProviderIssue | None = None


class WeatherAlertProvider(Protocol):
    """Retrieve current warning artifacts without discovering physical events."""

    async def fetch_active_alerts(self, *, now: datetime) -> WeatherAlertBatch: ...
