from disaster_monitor.infrastructure.composition import build_country_catalog
from disaster_monitor.infrastructure.configuration import Settings
from disaster_monitor.infrastructure.disaster.registrations import (
    build_provider_registrations,
)
from disaster_monitor.infrastructure.disaster.registrations.common import (
    RegistrationContext,
)
from disaster_monitor.infrastructure.disaster.registrations.gdacs import (
    GdacsRegistrations,
)
from disaster_monitor.infrastructure.disaster.registrations.gdacs import (
    build as build_gdacs,
)


def test_gdacs_registration_family_has_named_members() -> None:
    settings = Settings(country_catalog_automatic_updates=False)
    geography = build_country_catalog(settings)

    registrations = build_gdacs(RegistrationContext(settings, geography, None))

    assert isinstance(registrations, GdacsRegistrations)
    assert registrations.floods.source_id == "gdacs-floods"
    assert registrations.wildfires.source_id == "gdacs-wildfires"
    assert registrations.tropical_cyclones.source_id == "gdacs-tropical-cyclones"
    assert registrations.volcanic_eruptions.source_id == "gdacs-volcanic-eruptions"


def test_aggregate_provider_registration_order_and_identities_are_stable() -> None:
    settings = Settings(country_catalog_automatic_updates=False)

    registrations = build_provider_registrations(
        settings,
        build_country_catalog(settings),
        None,
    )

    actual = [
        (
            item.source_id,
            item.tier.value,
            tuple(sorted(role.value for role in item.capabilities.roles)),
            tuple(sorted(disaster.value for disaster in item.capabilities.disasters)),
            tuple(sorted(item.allowed_hosts)),
            item.event_provider is not None,
            item.worldwide_provider is not None,
            item.situation_provider is not None,
        )
        for item in registrations
    ]

    assert actual == [
        (
            "cems-gfm-floods",
            "primary",
            ("event_discovery",),
            ("flood",),
            ("data.eodc.eu", "stac.eodc.eu", "titiler.services.eodc.eu"),
            True,
            True,
            False,
        ),
        (
            "gdacs-floods",
            "secondary",
            ("event_discovery",),
            ("flood",),
            ("www.gdacs.org",),
            True,
            True,
            False,
        ),
        (
            "emsc-earthquakes",
            "secondary",
            ("event_discovery",),
            ("earthquake",),
            ("www.seismicportal.eu",),
            True,
            True,
            False,
        ),
        (
            "usgs-earthquakes",
            "secondary",
            ("event_discovery",),
            ("earthquake",),
            ("earthquake.usgs.gov",),
            True,
            True,
            False,
        ),
        (
            "nasa-eonet-wildfires",
            "primary",
            ("event_discovery",),
            ("wildfire",),
            ("eonet.gsfc.nasa.gov",),
            True,
            True,
            False,
        ),
        (
            "gdacs-wildfires",
            "secondary",
            ("event_discovery",),
            ("wildfire",),
            ("www.gdacs.org",),
            True,
            True,
            False,
        ),
        (
            "nasa-firms-observations",
            "secondary",
            ("situation_evidence",),
            ("wildfire",),
            ("firms.modaps.eosdis.nasa.gov",),
            False,
            False,
            True,
        ),
        (
            "nasa-coolr-landslides",
            "primary",
            ("event_discovery",),
            ("landslide",),
            ("gis.earthdata.nasa.gov",),
            True,
            True,
            False,
        ),
        (
            "copernicus-rapid-mapping-landslides",
            "secondary",
            ("situation_evidence",),
            ("landslide",),
            ("rapidmapping.emergency.copernicus.eu",),
            False,
            False,
            True,
        ),
        (
            "gdacs-tropical-cyclones",
            "secondary",
            ("event_discovery",),
            ("tropical_cyclone",),
            ("www.gdacs.org",),
            True,
            True,
            False,
        ),
        (
            "noaa-ibtracs-tracks",
            "secondary",
            ("situation_evidence",),
            ("tropical_cyclone",),
            ("www.ncei.noaa.gov",),
            False,
            False,
            True,
        ),
        (
            "smithsonian-usgs-volcanic-activity",
            "primary",
            ("event_discovery",),
            ("volcanic_eruption",),
            ("volcano.si.edu", "webservices.volcano.si.edu"),
            True,
            True,
            False,
        ),
        (
            "gdacs-volcanic-eruptions",
            "secondary",
            ("event_discovery",),
            ("volcanic_eruption",),
            ("www.gdacs.org",),
            True,
            True,
            False,
        ),
        (
            "reliefweb-situation-reports",
            "secondary",
            ("situation_evidence",),
            (
                "earthquake",
                "flood",
                "landslide",
                "tropical_cyclone",
                "volcanic_eruption",
                "wildfire",
            ),
            ("api.reliefweb.int", "reliefweb.int", "www.reliefweb.int"),
            False,
            False,
            True,
        ),
    ]
