"""Port for retrieving current disaster information."""

from typing import Protocol

from disaster_monitor.application.dto import DisasterInformationResult


class DisasterInformationProvider(Protocol):
    """Retrieve current reports for a deterministic disaster search query."""

    async def search(self, query: str) -> DisasterInformationResult:
        """Return recent reports ordered from newest to oldest."""
        ...
