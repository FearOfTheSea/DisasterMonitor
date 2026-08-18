"""Shared deterministic hazard aliases."""

from disaster_monitor.domain.disaster import Hazard

TROPICAL_CYCLONE_ALIASES: tuple[str, ...] = (
    "cyclone",
    "cyclones",
    "tropical cyclone",
    "tropical cyclones",
    "typhoon",
    "typhoons",
    "hurricane",
    "hurricanes",
    "tifón",
    "tifones",
    "huracán",
    "huracanes",
    "bão nhiệt đới",
    "台風",
)


def aliases_for(hazard: Hazard) -> tuple[str, ...]:
    """Return the maintained alias set for a hazard."""
    return TROPICAL_CYCLONE_ALIASES if hazard is Hazard.TROPICAL_CYCLONE else ()
