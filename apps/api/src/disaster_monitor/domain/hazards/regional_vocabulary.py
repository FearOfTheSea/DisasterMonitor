"""Bounded literal source wording; these aliases do not translate event facts."""

import re

from disaster_monitor.domain.disaster_types import Disaster

REGIONAL_HAZARDS = {
    Disaster.EARTHQUAKE: re.compile(
        r"\b(?:terremotos?|sismos?|s[eé]ismes?|gempa(?: bumi)?)\b", re.I
    ),
    Disaster.FLOOD: re.compile(r"\b(?:inundaci[oó]n(?:es)?|inondations?)\b", re.I),
    Disaster.WILDFIRE: re.compile(
        r"\b(?:incendios? forestal(?:es)?|"
        r"incendies? (?:de (?:la )?for[eê]t|forestiers?))\b",
        re.I,
    ),
    Disaster.LANDSLIDE: re.compile(
        r"\b(?:deslizamientos? de (?:tierra|ladera)|deslaves?|"
        r"glissements? de terrain|coul[eé]es? de boue)\b",
        re.I,
    ),
    Disaster.DROUGHT: re.compile(r"\b(?:sequ[ií]as?|s[eé]cheresses?)\b", re.I),
    Disaster.TROPICAL_CYCLONE: re.compile(
        r"\b(?:hurac[aá]n(?:es)?|tif[oó]n(?:es)?|cicl[oó]n(?:es)?|"
        r"tormentas? tropicales?|ouragans?|typhons?|temp[eê]tes? tropicales?)\b",
        re.I,
    ),
    Disaster.VOLCANIC_ERUPTION: re.compile(
        r"\b(?:erupci[oó]n(?:es)? volc[aá]nic[ao]s?|[eé]ruptions? volcaniques?)\b",
        re.I,
    ),
}
