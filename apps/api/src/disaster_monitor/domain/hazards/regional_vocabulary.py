"""Bounded literal source wording; these aliases do not translate event facts."""

import re

from disaster_monitor.domain.disaster_types import Disaster

TURKISH_EARTHQUAKE_ENDING = r"(?:i(?:n(?:de|den|in)?)?|de|den|e|le)?"
TURKISH_LANDSLIDE_ENDING = r"(?:ı(?:n(?:da|dan|ın)?)?|da|dan|a|la)?"
TURKISH_MULTIPLE_SLIDES = (
    rf"(?:heyelanlar{TURKISH_LANDSLIDE_ENDING}|"
    r"toprak\s+kaymaları(?:n(?:da|dan|ın)?)?|"
    r"kaya\s+düşmeleri(?:n(?:de|den|in)?)?)"
)
TURKISH_SOIL_SLIDE = (
    rf"(?:heyelan{TURKISH_LANDSLIDE_ENDING}|"
    r"toprak\s+kayması(?:n(?:da|dan|ın)?)?|"
    rf"kaya\s+düşmesi(?:n(?:de|den|in)?)?|{TURKISH_MULTIPLE_SLIDES})"
)
GERMAN_SOIL_SLIDE = (
    r"(?:Erdrutsch(?:es|en|e)?|(?:Kohle)?schlammlawinen?|"
    r"Felsst(?:urz(?:es)?|ürze[n]?))"
)
GERMAN_CALENDAR_MONTH = (
    r"(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|"
    r"Oktober|November|Dezember)"
)

REGIONAL_HAZARDS = {
    Disaster.EARTHQUAKE: re.compile(
        r"\b(?:terremotos?|sismos?|s[eé]ismes?|gempa(?: bumi)?|"
        rf"deprem(?:ler)?{TURKISH_EARTHQUAKE_ENDING})\b",
        re.I,
    ),
    Disaster.FLOOD: re.compile(
        r"\b(?:inundaci[oó]n(?:es)?|riadas?|inondations?|banjir|"
        r"enchentes?|enxurradas?|inundaç(?:ão|ões)|"
        r"(?:caminos?|carreteras?|calles?|viviendas?|casas?|barrios?|pueblos?|zonas?)"
        r"\s+inundad[oa]s?)\b",
        re.I,
    ),
    Disaster.WILDFIRE: re.compile(
        r"\b(?:incendios? forestal(?:es)?|"
        r"incendies? (?:de (?:la )?for[eê]t|forestiers?))\b",
        re.I,
    ),
    Disaster.LANDSLIDE: re.compile(
        r"\b(?:deslizamientos? de (?:tierra|ladera)|deslaves?|"
        r"glissements? de terrain|coul[eé]es? de boue|"
        r"(?:tanah )?longsor|deslizamentos?(?: de (?:terra|solo))?|"
        rf"desmoronamentos? de (?:terra|solo)|{GERMAN_SOIL_SLIDE}|"
        rf"{TURKISH_SOIL_SLIDE})\b",
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
