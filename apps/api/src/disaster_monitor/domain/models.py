"""Small framework-independent domain models."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MapView:
    """The browser's current map view, supplied as context to the assistant."""

    center_latitude: float
    center_longitude: float
    zoom: float


@dataclass(frozen=True, slots=True)
class MapQuestion:
    """A normalized user question and optional map context."""

    text: str
    conversation_id: str
    map_view: MapView | None = None
