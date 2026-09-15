from disaster_monitor.domain.disaster import Disaster
from disaster_monitor.domain.hazards.taxonomy import (
    DEFAULT_HAZARD_TAXONOMY,
    HazardIdentityKind,
)


def test_taxonomy_includes_slow_onset_drought_without_promoting_warning_types() -> None:
    drought = DEFAULT_HAZARD_TAXONOMY.require("drought")

    assert drought.disaster is Disaster.DROUGHT
    assert drought.identity_kind is HazardIdentityKind.SPATIAL_TIME_WINDOW
    assert drought.warning_event_codes == ("drought",)
    assert DEFAULT_HAZARD_TAXONOMY.physical_disaster_for_warning("Tsunami") is None


def test_taxonomy_resolves_aliases_without_iterating_a_fixed_enum() -> None:
    assert DEFAULT_HAZARD_TAXONOMY.resolve("river flooding").hazard_id == "flood"
    assert DEFAULT_HAZARD_TAXONOMY.resolve("khô hạn").hazard_id == "drought"
    assert tuple(
        item.hazard_id for item in DEFAULT_HAZARD_TAXONOMY.physical_hazards()
    ) == (
        "earthquake",
        "flood",
        "wildfire",
        "landslide",
        "tropical_cyclone",
        "volcanic_eruption",
        "drought",
    )
