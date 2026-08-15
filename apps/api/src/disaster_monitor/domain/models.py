"""Small framework-independent domain models."""

from dataclasses import dataclass
from math import isfinite


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


@dataclass(frozen=True, slots=True)
class MapNavigationAction:
    """A validated viewport-only action with no evidence or decision authority."""

    bounds: tuple[float, float, float, float]
    label: str
    max_zoom: float = 10.0

    def __post_init__(self) -> None:
        min_longitude, min_latitude, max_longitude, max_latitude = self.bounds
        if not all(isfinite(value) for value in self.bounds):
            raise ValueError("Map navigation bounds must be finite.")
        if not -180 <= min_longitude <= 180:
            raise ValueError("The minimum map longitude is invalid.")
        if max_longitude < min_longitude or max_longitude - min_longitude > 360:
            raise ValueError("The map longitude interval is invalid.")
        if not -90 <= min_latitude <= max_latitude <= 90:
            raise ValueError("The map latitude interval is invalid.")
        if not self.label.strip() or len(self.label) > 160:
            raise ValueError("A map navigation action requires a bounded label.")
        if not isfinite(self.max_zoom) or not 2 <= self.max_zoom <= 18:
            raise ValueError("Map navigation max zoom must be between 2 and 18.")
