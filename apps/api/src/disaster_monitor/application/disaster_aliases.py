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

VOLCANIC_ERUPTION_ALIASES: tuple[str, ...] = (
    "volcanic eruption",
    "volcanic eruptions",
    "volcano eruption",
    "volcano eruptions",
    "erupting volcano",
    "erupting volcanoes",
    "erupción volcánica",
    "erupciones volcánicas",
    "phun trào núi lửa",
    "火山噴火",
)


def aliases_for(disaster: Disaster) -> tuple[str, ...]:
    """Return the maintained alias set for a disaster."""
    if disaster is Disaster.TROPICAL_CYCLONE:
        return TROPICAL_CYCLONE_ALIASES
    if disaster is Disaster.VOLCANIC_ERUPTION:
        return VOLCANIC_ERUPTION_ALIASES
    return ()
