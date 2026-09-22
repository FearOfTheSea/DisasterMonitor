"""Human-reviewed, versioned disaster terminology packs."""

from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.domain.disaster_types import _is_aware


@dataclass(frozen=True, slots=True)
class TerminologyPack:
    language: str
    version: str
    reviewed_by: str
    reviewed_at: datetime
    terms: tuple[tuple[str, str], ...]
    human_reviewed: bool = True

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.language, self.version, self.reviewed_by)
        ):
            raise ValueError("Terminology packs require versioned review metadata.")
        if not _is_aware(self.reviewed_at):
            raise ValueError("Terminology review time must be timezone-aware.")
        if not self.human_reviewed:
            raise ValueError("Runtime model output is not a terminology pack.")
        keys = [key for key, _value in self.terms]
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("Terminology keys must be present and unique.")
        if any(not key.strip() or not value.strip() for key, value in self.terms):
            raise ValueError("Terminology entries must not be empty.")


__all__ = ["TerminologyPack"]
