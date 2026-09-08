from disaster_monitor.infrastructure.geography.static_geographic_region_catalog import (
    StaticGeographicRegionCatalog,
)


def test_resolves_provenanced_region_names_case_insensitively() -> None:
    catalog = StaticGeographicRegionCatalog()

    kermadec = catalog.find("KERMADEC ISLANDS REGION")
    loyalty = catalog.find("southeast of the Loyalty Islands")

    assert kermadec is not None
    assert kermadec.country_code == "NZL"
    assert kermadec.source_url == "https://gazetteer.linz.govt.nz/place/58783"
    assert loyalty is not None
    assert loyalty.country_code == "NCL"
    assert loyalty.source_url.startswith("https://gouv.nc/")


def test_does_not_match_region_names_inside_other_words() -> None:
    catalog = StaticGeographicRegionCatalog()

    assert catalog.find("A loyalty islands-themed exercise") is not None
    assert catalog.find("PseudoKermadec Islandsland") is None
