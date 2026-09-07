"""Scale-preserving interpretation of the currently admitted intensity notation."""

import math
import re
from dataclasses import dataclass
from enum import StrEnum


class IntensityScale(StrEnum):
    MODIFIED_MERCALLI = "mmi"
    JMA = "jma"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True, slots=True)
class IntensityReading:
    scale: IntensityScale
    level: float


def parse_intensity(value: float | str | None) -> IntensityReading | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return (
            IntensityReading(IntensityScale.UNSPECIFIED, float(value))
            if math.isfinite(value) and 1 <= value <= 7
            else None
        )
    normalized = value.translate(str.maketrans("０１２３４５６７", "01234567"))
    match = re.fullmatch(
        r"\s*(?:(?P<scale>MMI|JMA)\s*)?(?P<level>[1-7](?:\.\d+)?)(?P<suffix>[+-]?)\s*",
        normalized,
        re.IGNORECASE,
    )
    if match is None:
        return None
    level = float(match.group("level"))
    suffix = match.group("suffix")
    if suffix:
        level = float(int(level)) - (0.5 if suffix == "-" else 0)
    if not 1 <= level <= 7:
        return None
    scale = (
        IntensityScale.MODIFIED_MERCALLI
        if (match.group("scale") or "").upper() == "MMI"
        else IntensityScale.JMA
    )
    return IntensityReading(scale, level)
