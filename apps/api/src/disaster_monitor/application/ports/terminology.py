"""Reader seam for source-controlled terminology packs."""

from typing import Protocol

from disaster_monitor.domain.terminology import TerminologyPack


class TerminologyPackReader(Protocol):
    def read(self, language: str) -> TerminologyPack: ...


__all__ = ["TerminologyPackReader"]
