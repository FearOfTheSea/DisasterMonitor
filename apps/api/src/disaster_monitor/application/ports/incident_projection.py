"""Persistence boundary for the worldwide incident projection."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IncidentProjectionRecord:
    """One immutable, queryable projection snapshot."""

    projection_id: str
    snapshot_version: str
    retrieved_at: datetime
    created_at: datetime
    payload_json: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.projection_id,
                self.snapshot_version,
                self.payload_json,
            )
        ):
            raise ValueError("Incident projections require stable identity and data.")
        if self.retrieved_at.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("Incident projection times must be timezone-aware.")


class IncidentProjectionStore(Protocol):
    """Append and read the latest worldwide incident projection."""

    async def append_incident_projection(
        self, projection: IncidentProjectionRecord
    ) -> bool: ...

    async def latest_incident_projection(
        self,
    ) -> IncidentProjectionRecord | None: ...
