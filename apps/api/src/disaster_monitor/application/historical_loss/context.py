"""Bound retrospective loss data to pre-event preparedness context."""

from collections.abc import Callable
from datetime import UTC, datetime

from disaster_monitor.application.ports.historical_loss import HistoricalLossProvider
from disaster_monitor.domain.disaster_types import Disaster, _is_aware
from disaster_monitor.domain.historical_loss import HistoricalLossContext

_LIMITATIONS = (
    "Historical losses are preparedness and comparison context, not evidence of "
    "current impact.",
    "Reporting methods, coverage, currencies, boundaries, and completeness vary by "
    "dataset and period.",
)


class HistoricalLossContextService:
    def __init__(
        self,
        providers: tuple[HistoricalLossProvider, ...],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._providers = providers
        self._clock = clock

    async def for_event(
        self,
        *,
        country_code: str,
        hazard: Disaster,
        event_occurred_at: datetime,
        limit: int = 100,
    ) -> HistoricalLossContext:
        normalized_country = country_code.strip().upper()
        if len(normalized_country) != 3:
            raise ValueError("Historical context requires an ISO3 country code.")
        if not _is_aware(event_occurred_at):
            raise ValueError("Event occurrence time must be timezone-aware.")
        if not 1 <= limit <= 1_000:
            raise ValueError("Historical context limit must be between 1 and 1000.")
        now = self._clock()
        records = []
        gaps = []
        for provider in self._providers:
            try:
                returned = await provider.records(
                    country_code=normalized_country, hazard=hazard
                )
            except Exception:
                gaps.append(
                    f"{provider.source_id} was unavailable; no historical absence "
                    "can be inferred."
                )
                continue
            for record in returned:
                if (
                    record.country_code.upper() == normalized_country
                    and record.hazard is hazard
                    and record.occurred_at < event_occurred_at
                    and record.retrieved_at <= now
                ):
                    records.append(record)
        selected = tuple(
            sorted(records, key=lambda item: item.occurred_at, reverse=True)[:limit]
        )
        return HistoricalLossContext(
            country_code=normalized_country,
            hazard=hazard,
            records=selected,
            gaps=tuple(gaps),
            limitations=_LIMITATIONS,
        )


__all__ = ["HistoricalLossContextService"]
