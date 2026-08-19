"""Shared deterministic disaster aliases."""

from disaster_monitor.domain.disaster import Disaster

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


def aliases_for(disaster: Disaster) -> tuple[str, ...]:
    """Return the maintained alias set for a disaster."""
    return TROPICAL_CYCLONE_ALIASES if disaster is Disaster.TROPICAL_CYCLONE else ()
