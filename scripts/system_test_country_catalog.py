"""Deterministic country metadata for the browser system test."""

from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)

_SYSTEM_COUNTRIES: tuple[dict[str, object], ...] = (
    {
        "alpha3": "USA",
        "name": "United States",
        "aliases": ["US", "USA"],
        "bounds": [51.0, 53.0, -171.0, -169.0],
        "polygons": [[[51.0, -171.0], [53.0, -171.0], [53.0, -169.0], [51.0, -169.0]]],
    },
    {
        "alpha3": "THA",
        "name": "Thailand",
        "aliases": ["TH"],
        "bounds": [14.0, 16.0, 104.0, 106.0],
        "polygons": [[[14.0, 104.0], [16.0, 104.0], [16.0, 106.0], [14.0, 106.0]]],
    },
    {
        "alpha3": "BRA",
        "name": "Brazil",
        "aliases": ["BR"],
        "bounds": [-11.0, -9.0, -56.0, -54.0],
        "polygons": [[[-11.0, -56.0], [-9.0, -56.0], [-9.0, -54.0], [-11.0, -54.0]]],
    },
    {
        "alpha3": "TWN",
        "name": "Taiwan",
        "aliases": ["TW"],
        "bounds": [22.0, 25.0, 120.0, 122.0],
        "polygons": [[[22.0, 120.0], [25.0, 120.0], [25.0, 122.0], [22.0, 122.0]]],
    },
    {
        "alpha3": "PHL",
        "name": "Philippines",
        "aliases": ["PH"],
        "bounds": [5.0, 21.0, 116.0, 127.0],
        "polygons": [[[5.0, 116.0], [21.0, 116.0], [21.0, 127.0], [5.0, 127.0]]],
    },
    {
        "alpha3": "TZA",
        "name": "Tanzania",
        "aliases": ["TZ"],
        "bounds": [-4.0, -2.0, 35.0, 37.0],
        "polygons": [[[-4.0, 35.0], [-2.0, 35.0], [-2.0, 37.0], [-4.0, 37.0]]],
    },
    {
        "alpha3": "JPN",
        "name": "Japan",
        "aliases": ["JP"],
        "bounds": [24.0, 46.0, 123.0, 146.0],
        "polygons": [[[24.0, 123.0], [46.0, 123.0], [46.0, 146.0], [24.0, 146.0]]],
    },
    {
        "alpha3": "VEN",
        "name": "Venezuela",
        "aliases": ["VE"],
        "bounds": [0.0, 13.0, -74.0, -59.0],
        "polygons": [[[0.0, -74.0], [13.0, -74.0], [13.0, -59.0], [0.0, -59.0]]],
    },
)


def build_system_country_catalog() -> StaticCountryCatalog:
    catalog = StaticCountryCatalog()
    catalog.activate_payload(
        {
            "metadata": {
                "version": "system-test.v1",
                "schema_version": "2.0.0",
                "country_count": len(_SYSTEM_COUNTRIES),
            },
            "countries": list(_SYSTEM_COUNTRIES),
        }
    )
    return catalog
