"""Provider seam for reviewed historical-loss datasets."""

from typing import Protocol

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.historical_loss import HistoricalLossRecord


class HistoricalLossProvider(Protocol):
    source_id: str

    async def records(
        self, *, country_code: str, hazard: Disaster
    ) -> tuple[HistoricalLossRecord, ...]: ...


__all__ = ["HistoricalLossProvider"]
