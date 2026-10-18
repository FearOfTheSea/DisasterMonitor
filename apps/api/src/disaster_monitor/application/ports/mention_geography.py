"""Resolve source-named places without asserting an event or damage location."""

from dataclasses import dataclass
from typing import Literal, Protocol

from disaster_monitor.domain.events import EventGeometry


@dataclass(frozen=True, slots=True)
class PlaceResolution:
    status: Literal["resolved", "ambiguous", "unresolved", "unavailable"]
    geometry: EventGeometry | None = None
    detail: str = ""


class MentionPlaceResolver(Protocol):
    async def resolve(
        self, place: str, country_context: str | None
    ) -> PlaceResolution: ...
