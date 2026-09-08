"""Deterministic country association policy for worldwide incident discovery."""

from dataclasses import dataclass
from enum import StrEnum

from disaster_monitor.application.disaster import WorldwideDisasterEvent
from disaster_monitor.application.ports.geographic_regions import (
    GeographicRegionCatalog,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.disaster import Country


class CountryAssociationBasis(StrEnum):
    COORDINATE_POLYGON = "coordinate_polygon"
    SOURCE_MENTION = "source_mention"
    NAMED_REGION = "named_region"
    NEARBY_BOUNDARY = "nearby_boundary"


@dataclass(frozen=True, slots=True)
class IncidentCountryAssociation:
    country_code: str
    country_name: str
    basis: CountryAssociationBasis
    distance_km: float | None = None


class IncidentCountryResolver:
    def __init__(
        self,
        country_catalog: CountryCatalog,
        region_catalog: GeographicRegionCatalog | None = None,
        *,
        maximum_nearby_distance_km: float = 100.0,
    ) -> None:
        if maximum_nearby_distance_km <= 0:
            raise ValueError("maximum_nearby_distance_km must be positive.")
        self._countries = country_catalog
        self._regions = region_catalog
        self._maximum_nearby_distance_km = maximum_nearby_distance_km

    def resolve(
        self, event: WorldwideDisasterEvent
    ) -> IncidentCountryAssociation | None:
        coordinate = _representative_coordinate(event)
        if coordinate is not None:
            latitude, longitude = coordinate
            containing = tuple(
                country
                for country in self._countries.countries()
                if self._countries.contains(country, latitude, longitude)
            )
            if containing:
                return _association(
                    min(containing, key=lambda country: country.alpha3_code),
                    CountryAssociationBasis.COORDINATE_POLYGON,
                )

        mentioned = self._countries.find_mentions(event.location)
        if mentioned:
            return _association(mentioned[0], CountryAssociationBasis.SOURCE_MENTION)

        region_match = self._regions.find(event.location) if self._regions else None
        if region_match is not None:
            country = self._countries.get_by_alpha3(region_match.country_code)
            if country is not None:
                return _association(country, CountryAssociationBasis.NAMED_REGION)

        if coordinate is None:
            return None
        latitude, longitude = coordinate
        nearest = _nearest_country(self._countries.countries(), latitude, longitude)
        if nearest is None or nearest[0] > self._maximum_nearby_distance_km:
            return None
        distance_km, country = nearest
        return _association(
            country,
            CountryAssociationBasis.NEARBY_BOUNDARY,
            distance_km=round(distance_km, 1),
        )


def _representative_coordinate(
    event: WorldwideDisasterEvent,
) -> tuple[float, float] | None:
    if event.geometry is None or not event.geometry.coordinates:
        return None
    coordinate = event.geometry.coordinates[0]
    return coordinate.latitude, coordinate.longitude


def _nearest_country(
    countries: tuple[Country, ...], latitude: float, longitude: float
) -> tuple[float, Country] | None:
    candidates = tuple(
        (distance, country)
        for country in countries
        if (
            distance := country.geographic_area.distance_to_boundary_km(
                latitude, longitude
            )
        )
        is not None
    )
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1].alpha3_code))


def _association(
    country: Country,
    basis: CountryAssociationBasis,
    *,
    distance_km: float | None = None,
) -> IncidentCountryAssociation:
    return IncidentCountryAssociation(
        country_code=country.alpha3_code,
        country_name=country.canonical_name,
        basis=basis,
        distance_km=distance_km,
    )
