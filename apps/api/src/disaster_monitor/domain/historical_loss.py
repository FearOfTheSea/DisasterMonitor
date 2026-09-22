"""Retrospective disaster-loss context that cannot represent current impact."""

from dataclasses import dataclass
from datetime import datetime

from disaster_monitor.domain.disaster_types import Disaster, _is_aware


@dataclass(frozen=True, slots=True)
class HistoricalLossRecord:
    record_id: str
    dataset_id: str
    source_id: str
    country_code: str
    hazard: Disaster
    event_name: str
    occurred_at: datetime
    fatalities: int | None
    people_affected: int | None
    economic_loss_usd: float | None
    source_url: str
    license_name: str
    dataset_updated_at: datetime
    retrieved_at: datetime
    role: str = "historical_preparedness_context"
    current_impact_inference: bool = False

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.record_id,
                self.dataset_id,
                self.source_id,
                self.country_code,
                self.event_name,
                self.license_name,
            )
        ):
            raise ValueError("Historical losses require source and dataset identity.")
        if len(self.country_code.strip()) != 3:
            raise ValueError("Historical losses require an ISO3 country code.")
        if not self.source_url.startswith("https://"):
            raise ValueError("Historical losses require an HTTPS source URL.")
        for name, timestamp in (
            ("occurred_at", self.occurred_at),
            ("dataset_updated_at", self.dataset_updated_at),
            ("retrieved_at", self.retrieved_at),
        ):
            if not _is_aware(timestamp):
                raise ValueError(f"{name} must be timezone-aware.")
        for count in (self.fatalities, self.people_affected):
            if count is not None and count < 0:
                raise ValueError("Historical loss counts cannot be negative.")
        if self.economic_loss_usd is not None and self.economic_loss_usd < 0:
            raise ValueError("Historical economic loss cannot be negative.")
        if (
            self.role != "historical_preparedness_context"
            or self.current_impact_inference
        ):
            raise ValueError("Historical loss records cannot assert current impact.")


@dataclass(frozen=True, slots=True)
class HistoricalLossContext:
    country_code: str
    hazard: Disaster
    records: tuple[HistoricalLossRecord, ...]
    gaps: tuple[str, ...]
    limitations: tuple[str, ...]
    role: str = "historical_preparedness_context"
    current_impact_inference: bool = False

    def __post_init__(self) -> None:
        if self.role != "historical_preparedness_context":
            raise ValueError("Historical context must retain its retrospective role.")
        if self.current_impact_inference:
            raise ValueError("Historical context cannot infer current impact.")


__all__ = ["HistoricalLossContext", "HistoricalLossRecord"]
