"""Consumer-owned contracts for desktop evidence, without an assistant runtime."""

from dataclasses import dataclass
from typing import Protocol

from disaster_monitor.application.media import DisasterMediaGallery, MediaEventContext
from disaster_monitor.application.ports.weather_alerts import WeatherAlertBatch
from disaster_monitor.domain.events import DisasterEvent
from disaster_monitor.domain.exposure import ExposureAnalysis, ExposureGeometry
from disaster_monitor.domain.hazard_context import BaselineVulnerabilityContext
from disaster_monitor.domain.humanitarian import HumanitarianContextSnapshot
from disaster_monitor.domain.imagery.regions import MultiPolygon


@dataclass(frozen=True, slots=True)
class IncidentEvidenceContext:
    media: MediaEventContext
    event: DisasterEvent | None
    geometry: MultiPolygon | None


class IncidentEvidenceReader(Protocol):
    async def read(self, identifier: str) -> IncidentEvidenceContext: ...


class ExposureReader(Protocol):
    async def execute(self, geometry: ExposureGeometry) -> ExposureAnalysis: ...


class HumanitarianReader(Protocol):
    async def for_country(
        self, country_code: str, *, event_id: str | None = None
    ) -> HumanitarianContextSnapshot: ...


class BaselineReader(Protocol):
    def lookup(self, place_code: str) -> BaselineVulnerabilityContext | None: ...


class EventMediaReader(Protocol):
    async def discover(
        self, context: MediaEventContext, *, cursor: str | None = None
    ) -> DisasterMediaGallery | None: ...


class CurrentWarningReader(Protocol):
    async def current_messages(self) -> WeatherAlertBatch: ...
