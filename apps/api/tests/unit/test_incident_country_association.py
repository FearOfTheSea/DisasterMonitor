from dataclasses import dataclass
from datetime import UTC, datetime

from disaster_monitor.application.disaster import WorldwideDisasterEvent
from disaster_monitor.application.incidents.country_association import (
    CountryAssociationBasis,
    IncidentCountryResolver,
)
from disaster_monitor.application.ports.geographic_regions import (
    GeographicRegionCountryMatch,
)
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    GeographicArea,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)


def _country(code: str, name: str, bounds: tuple[float, float, float, float]):
    min_latitude, max_latitude, min_longitude, max_longitude = bounds
    return Country(
        alpha3_code=code,
        canonical_name=name,
        aliases=(),
        geographic_area=GeographicArea(
            min_latitude,
            max_latitude,
            min_longitude,
            max_longitude,
            polygons=(
                (
                    (min_latitude, min_longitude),
                    (min_latitude, max_longitude),
                    (max_latitude, max_longitude),
                    (max_latitude, min_longitude),
                ),
            ),
        ),
    )


ITALY = _country("ITA", "Italy", (36.0, 47.0, 7.0, 18.0))
NEW_ZEALAND = _country("NZL", "New Zealand", (-47.5, -34.0, 166.0, 179.0))


class FakeCountryCatalog:
    def __init__(self, countries: tuple[Country, ...]) -> None:
        self._countries = countries

    def countries(self) -> tuple[Country, ...]:
        return self._countries

    def find_mentions(self, text: str) -> tuple[Country, ...]:
        return tuple(
            country
            for country in self._countries
            if country.canonical_name.casefold() in text.casefold()
        )

    def get_by_alpha3(self, alpha3_code: str) -> Country | None:
        return next(
            (
                country
                for country in self._countries
                if country.alpha3_code == alpha3_code.upper()
            ),
            None,
        )

    def contains(self, country: Country, latitude: float, longitude: float) -> bool:
        return country.geographic_area.contains(latitude, longitude)


@dataclass
class FakeRegionCatalog:
    match: GeographicRegionCountryMatch | None = None

    def find(self, text: str) -> GeographicRegionCountryMatch | None:
        return self.match if self.match and self.match.matched_name in text else None


def _event(location: str, latitude: float, longitude: float):
    source = SourceReference(
        source_id="fixture",
        publisher="Fixture",
        title="Fixture event",
        canonical_url="https://fixture.example/event",
        published_at=None,
        updated_at=None,
        retrieved_at=datetime(2026, 9, 8, tzinfo=UTC),
        authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
    )
    return WorldwideDisasterEvent(
        event_id="fixture-event",
        disaster=Disaster.EARTHQUAKE,
        location=location,
        event_time=source.retrieved_at,
        source=source,
        geometry=point_event_geometry(latitude, longitude, source),
    )


def test_prefers_coordinate_membership_over_source_text() -> None:
    resolver = IncidentCountryResolver(
        FakeCountryCatalog((ITALY, NEW_ZEALAND)), FakeRegionCatalog()
    )

    association = resolver.resolve(_event("New Zealand bulletin region", 42.0, 12.0))

    assert association is not None
    assert association.country_code == "ITA"
    assert association.country_name == "Italy"
    assert association.basis is CountryAssociationBasis.COORDINATE_POLYGON
    assert association.distance_km is None


def test_uses_explicit_country_mention_for_offshore_event() -> None:
    resolver = IncidentCountryResolver(
        FakeCountryCatalog((ITALY, NEW_ZEALAND)), FakeRegionCatalog()
    )

    association = resolver.resolve(_event("Offshore New Zealand", -30.0, 178.0))

    assert association is not None
    assert association.country_code == "NZL"
    assert association.basis is CountryAssociationBasis.SOURCE_MENTION


def test_uses_provenanced_named_region_before_nearest_land() -> None:
    resolver = IncidentCountryResolver(
        FakeCountryCatalog((ITALY, NEW_ZEALAND)),
        FakeRegionCatalog(
            GeographicRegionCountryMatch(
                matched_name="Kermadec Islands",
                country_code="NZL",
                source_url="https://gazetteer.linz.govt.nz/place/58783",
            )
        ),
    )

    association = resolver.resolve(_event("Kermadec Islands region", -31.2, 178.7))

    assert association is not None
    assert association.country_code == "NZL"
    assert association.basis is CountryAssociationBasis.NAMED_REGION


def test_uses_only_bounded_nearby_country_associations() -> None:
    resolver = IncidentCountryResolver(
        FakeCountryCatalog((ITALY, NEW_ZEALAND)),
        FakeRegionCatalog(),
        maximum_nearby_distance_km=100.0,
    )

    nearby = resolver.resolve(_event("Provider acquisition 1", 40.4, 18.1))
    unresolved = resolver.resolve(_event("Open ocean", 0.0, 0.0))

    assert nearby is not None
    assert nearby.country_code == "ITA"
    assert nearby.basis is CountryAssociationBasis.NEARBY_BOUNDARY
    assert nearby.distance_km is not None and nearby.distance_km < 100
    assert unresolved is None
