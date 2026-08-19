"""The single maintained source of deterministic disaster vocabulary."""

import re

from disaster_monitor.domain.disaster import Disaster

DISASTER_ALIASES: dict[Disaster, tuple[str, ...]] = {
    Disaster.EARTHQUAKE: (
        "earthquake",
        "earthquakes",
        "quake",
        "quakes",
        "terremoto",
        "terremotos",
        "động đất",
        "地震",
    ),
    Disaster.FLOOD: (
        "flood",
        "floods",
        "flooding",
        "inundación",
        "inundaciones",
        "lũ lụt",
        "洪水",
    ),
    Disaster.WILDFIRE: (
        "wildfire",
        "wildfires",
        "forest fire",
        "forest fires",
        "incendio forestal",
        "cháy rừng",
        "山火事",
    ),
    Disaster.LANDSLIDE: (
        "landslide",
        "landslides",
        "deslizamiento de tierra",
        "sạt lở đất",
        "地滑り",
    ),
    Disaster.TROPICAL_CYCLONE: (
        "typhoon",
        "typhoons",
        "hurricane",
        "hurricanes",
        "cyclone",
        "cyclones",
        "tropical cyclone",
        "tropical cyclones",
        "tifón",
        "huracán",
        "bão nhiệt đới",
        "台風",
    ),
    Disaster.VOLCANIC_ERUPTION: (
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
    ),
}


def _validate_alias_catalog() -> None:
    if set(DISASTER_ALIASES) != set(Disaster):
        raise RuntimeError(
            "The disaster alias catalog must cover every Disaster value."
        )


_validate_alias_catalog()


def aliases_for(disaster: Disaster) -> tuple[str, ...]:
    """Return the maintained alias set for a disaster."""
    return DISASTER_ALIASES[disaster]


def recognized_disasters(text: str) -> tuple[Disaster, ...]:
    """Return disasters whose maintained aliases occur at a safe text boundary."""
    return tuple(
        disaster
        for disaster, aliases in DISASTER_ALIASES.items()
        if any(_matches_alias(text, alias) for alias in aliases)
    )


def _matches_alias(text: str, alias: str) -> bool:
    boundary = r"[A-Za-z0-9_]" if not alias.isascii() else r"\w"
    return bool(
        re.search(rf"(?<!{boundary}){re.escape(alias)}(?!{boundary})", text, re.I)
    )
