"""Compatibility facade for country-catalog update infrastructure."""

from disaster_monitor.infrastructure.geography.country_catalog_generation import (
    build_country_catalog_payload,
    serialize_country_catalog,
)
from disaster_monitor.infrastructure.geography.country_catalog_source import (
    CountryCatalogSource,
    CountryCatalogSourceSnapshot,
    NaturalEarthCountryCatalogSource,
)
from disaster_monitor.infrastructure.geography.country_catalog_storage import (
    VersionedCountryCatalogStore,
)
from disaster_monitor.infrastructure.geography.country_catalog_updater import (
    AutonomousCountryCatalogUpdater,
    CountryCatalogAutomation,
    next_country_catalog_update_at,
)

__all__ = [
    "AutonomousCountryCatalogUpdater",
    "CountryCatalogAutomation",
    "CountryCatalogSource",
    "CountryCatalogSourceSnapshot",
    "NaturalEarthCountryCatalogSource",
    "VersionedCountryCatalogStore",
    "build_country_catalog_payload",
    "next_country_catalog_update_at",
    "serialize_country_catalog",
]
