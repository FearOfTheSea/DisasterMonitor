"""Bounded map tools whose effects are validated and application-owned."""

from disaster_monitor.application.disaster import SelectedEventSummary
from disaster_monitor.application.dto import ModelTool, ModelToolCall
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.disaster import Country
from disaster_monitor.domain.models import MapNavigationAction
from disaster_monitor.domain.multimodal import (
    CommonOperationalPicture,
    GeoLineString,
    GeoPoint,
    GeoPolygon,
    MapGeometry,
)

FIT_COUNTRY_TOOL = "fit_country"


class MapNavigationService:
    """Expose and execute only allowlisted, reversible viewport operations."""

    def __init__(self, countries: CountryCatalog) -> None:
        self._countries = countries

    def model_tools(self) -> tuple[ModelTool, ...]:
        countries = self._countries.countries()
        codes = [country.alpha3_code for country in countries]
        labels = "; ".join(
            f"{country.alpha3_code} = {country.canonical_name}" for country in countries
        )
        return (
            ModelTool(
                name=FIT_COUNTRY_TOOL,
                description=(
                    "Move and zoom the browser map to a supported country only when "
                    "the user explicitly asks to navigate, show, locate, center, pan, "
                    "or zoom the map. Resolve the user's country name to the listed "
                    "code yourself; do not ask the user for a code. This changes only "
                    "the viewport and supplies no disaster evidence."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "country_code": {
                            "type": "string",
                            "enum": codes,
                            "description": f"Supported country mappings: {labels}.",
                        }
                    },
                    "required": ["country_code"],
                    "additionalProperties": False,
                },
            ),
        )

    def execute_model_calls(
        self, calls: tuple[ModelToolCall, ...], *, admitted_text: str
    ) -> MapNavigationAction | None:
        if len(calls) != 1:
            return None
        call = calls[0]
        if call.name != FIT_COUNTRY_TOOL or set(call.arguments) != {"country_code"}:
            return None
        code = call.arguments.get("country_code")
        if not isinstance(code, str):
            return None
        country = self._countries.get_by_alpha3(code)
        admitted_countries = self._countries.find_mentions(admitted_text)
        if (
            country is None
            or len(admitted_countries) != 1
            or admitted_countries[0].alpha3_code != country.alpha3_code
        ):
            return None
        return self.for_country(country)

    def for_disaster_context(
        self,
        *,
        cop: CommonOperationalPicture | None,
        selected_event: SelectedEventSummary | None,
        country: Country | None,
    ) -> MapNavigationAction | None:
        if cop is not None:
            bounds = _cop_bounds(cop)
            if bounds is not None:
                return MapNavigationAction(bounds, "Common operational picture")
        if (
            selected_event is not None
            and selected_event.longitude is not None
            and selected_event.latitude is not None
        ):
            return MapNavigationAction(
                (
                    selected_event.longitude,
                    selected_event.latitude,
                    selected_event.longitude,
                    selected_event.latitude,
                ),
                selected_event.location,
            )
        return self.for_country(country) if country is not None else None

    @staticmethod
    def for_country(country: Country) -> MapNavigationAction:
        area = country.geographic_area
        return MapNavigationAction(
            (
                area.min_longitude,
                area.min_latitude,
                area.max_longitude,
                area.max_latitude,
            ),
            country.canonical_name,
        )


def _cop_bounds(
    cop: CommonOperationalPicture,
) -> tuple[float, float, float, float] | None:
    points = [
        point
        for layer in cop.layers
        for feature in layer.features
        for point in _geometry_points(feature.geometry)
    ]
    if not points:
        return None
    min_longitude, max_longitude = _smallest_longitude_interval(
        [point.longitude for point in points]
    )
    return (
        min_longitude,
        min(point.latitude for point in points),
        max_longitude,
        max(point.latitude for point in points),
    )


def _geometry_points(geometry: MapGeometry) -> tuple[GeoPoint, ...]:
    if isinstance(geometry, GeoPoint):
        return (geometry,)
    if isinstance(geometry, GeoLineString):
        return geometry.points
    if isinstance(geometry, GeoPolygon):
        return tuple(point for ring in geometry.rings for point in ring)
    return ()


def _smallest_longitude_interval(longitudes: list[float]) -> tuple[float, float]:
    sorted_longitudes = sorted(
        ((longitude + 180) % 360) - 180 for longitude in longitudes
    )
    if len(sorted_longitudes) == 1:
        return sorted_longitudes[0], sorted_longitudes[0]
    largest_gap = float("-inf")
    interval_start = sorted_longitudes[0]
    interval_end = sorted_longitudes[-1]
    for index, current in enumerate(sorted_longitudes):
        following = (
            sorted_longitudes[0] + 360
            if index == len(sorted_longitudes) - 1
            else sorted_longitudes[index + 1]
        )
        gap = following - current
        if gap > largest_gap:
            largest_gap = gap
            interval_start = following
            interval_end = current + 360
    while interval_start > 180:
        interval_start -= 360
        interval_end -= 360
    return interval_start, interval_end
