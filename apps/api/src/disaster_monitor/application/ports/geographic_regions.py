"""Port for deterministic named-region country associations."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GeographicRegionCountryMatch:
    matched_name: str
    country_code: str
    source_url: str


class GeographicRegionCatalog(Protocol):
    def find(self, text: str) -> GeographicRegionCountryMatch | None: ...
