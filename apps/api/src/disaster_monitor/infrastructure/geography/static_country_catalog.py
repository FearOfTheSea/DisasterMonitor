"""Packaged deterministic country catalog."""

import json
import re
from importlib.resources import files

from disaster_monitor.domain.disaster import (
    BoundaryValidationQuality,
    Country,
    GeographicArea,
)


class StaticCountryCatalog:
    """Resolve exact aliases from the versioned packaged metadata resource."""

    def __init__(self) -> None:
        resource = files(
            "disaster_monitor.infrastructure.geography.resources"
        ).joinpath("countries.v1.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
        self.metadata = payload["metadata"]
        self._countries = tuple(
            Country(
                alpha3_code=item["alpha3"],
                canonical_name=item["name"],
                aliases=tuple(item["aliases"]),
                default_timezone=item.get("timezone"),
                geographic_area=GeographicArea(
                    min_latitude=item["bounds"][0],
                    max_latitude=item["bounds"][1],
                    min_longitude=item["bounds"][2],
                    max_longitude=item["bounds"][3],
                    validation_quality=(
                        BoundaryValidationQuality.POLYGON
                        if item.get("polygons")
                        else BoundaryValidationQuality.BOUNDING_BOX
                    ),
                    polygons=tuple(
                        tuple((float(point[0]), float(point[1])) for point in polygon)
                        for polygon in item.get("polygons", ())
                    ),
                ),
            )
            for item in payload["countries"]
        )
        self._by_code = {country.alpha3_code: country for country in self._countries}

    def countries(self) -> tuple[Country, ...]:
        return self._countries

    def find_mentions(self, text: str) -> tuple[Country, ...]:
        found: list[Country] = []
        for country in self._countries:
            terms = (
                country.canonical_name,
                country.alpha3_code,
                *country.aliases,
            )
            if any(_matches_term(text, term) for term in terms):
                found.append(country)
        return tuple(found)

    def get_by_alpha3(self, alpha3_code: str) -> Country | None:
        return self._by_code.get(alpha3_code.upper())

    def contains(self, country: Country, latitude: float, longitude: float) -> bool:
        return country.geographic_area.contains(latitude, longitude)


def _matches_term(text: str, term: str) -> bool:
    boundary = r"[A-Za-z0-9_]" if not term.isascii() else r"\w"
    return bool(
        re.search(rf"(?<!{boundary}){re.escape(term)}(?!{boundary})", text, re.I)
    )
