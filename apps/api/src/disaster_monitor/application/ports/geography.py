"""Port for deterministic country metadata and coordinate validation."""

from typing import Protocol

from disaster_monitor.domain.disaster import Country


class CountryCatalog(Protocol):
    """Resolve only exact canonical names, codes, and declared aliases."""

    def countries(self) -> tuple[Country, ...]: ...

    def find_mentions(self, text: str) -> tuple[Country, ...]: ...

    def get_by_alpha3(self, alpha3_code: str) -> Country | None: ...

    def contains(self, country: Country, latitude: float, longitude: float) -> bool: ...
