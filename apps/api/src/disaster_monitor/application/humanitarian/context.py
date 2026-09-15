"""Assemble contextual indicators without converting them into event impacts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ports.humanitarian import (
    HumanitarianIndicatorProvider,
    OperationalPresenceProvider,
)
from disaster_monitor.domain.humanitarian import (
    ContextAvailability,
    HumanitarianContextSnapshot,
    HumanitarianIndicator,
    HumanitarianIndicatorKind,
    OperationalPresence,
)

_MAXIMUM_AGES = {
    HumanitarianIndicatorKind.BASELINE_POPULATION: timedelta(days=730),
    HumanitarianIndicatorKind.DISPLACED_PEOPLE: timedelta(days=120),
    HumanitarianIndicatorKind.FOOD_INSECURITY: timedelta(days=365),
}


class HumanitarianContextService:
    def __init__(
        self,
        *,
        indicator_providers: tuple[HumanitarianIndicatorProvider, ...] = (),
        presence_providers: tuple[OperationalPresenceProvider, ...] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._indicator_providers = indicator_providers
        self._presence_providers = presence_providers
        self._clock = clock

    async def for_country(
        self, country_code: str, *, event_id: str | None = None
    ) -> HumanitarianContextSnapshot:
        normalized_country = country_code.strip().upper()
        if len(normalized_country) != 3 or not normalized_country.isalpha():
            raise ValueError("Humanitarian context requires an ISO alpha-3 code.")
        now = self._clock()
        indicator_results = await asyncio.gather(
            *(
                provider.indicators(normalized_country)
                for provider in self._indicator_providers
            ),
            return_exceptions=True,
        )
        presence_results = await asyncio.gather(
            *(
                provider.operational_presence(normalized_country)
                for provider in self._presence_providers
            ),
            return_exceptions=True,
        )
        indicators: list[HumanitarianIndicator] = []
        presence: list[OperationalPresence] = []
        gaps: list[str] = []
        for indicator_provider, indicator_result in zip(
            self._indicator_providers, indicator_results, strict=True
        ):
            if isinstance(indicator_result, BaseException):
                gaps.append(
                    f"{indicator_provider.source_id} was unavailable; "
                    "no absence can be inferred."
                )
                continue
            indicators.extend(self._classify_freshness(indicator_result, now=now))
        for presence_provider, presence_result in zip(
            self._presence_providers, presence_results, strict=True
        ):
            if isinstance(presence_result, BaseException):
                gaps.append(
                    f"{presence_provider.source_id} was unavailable; "
                    "no absence can be inferred."
                )
                continue
            presence.extend(presence_result)
        indicators.sort(
            key=lambda item: (
                list(HumanitarianIndicatorKind).index(item.kind),
                item.admin1_code or "",
                item.indicator_id,
            )
        )
        presence.sort(
            key=lambda item: (
                item.organization.casefold(),
                item.sector,
                item.presence_id,
            )
        )
        if indicators or presence:
            availability = (
                ContextAvailability.PARTIAL
                if gaps or any(item.stale for item in indicators)
                else ContextAvailability.AVAILABLE
            )
        elif gaps:
            availability = ContextAvailability.UNAVAILABLE
        else:
            availability = ContextAvailability.NO_DATA
            gaps.append(
                "No matching public humanitarian context was returned; this is not "
                "evidence of no need."
            )
        return HumanitarianContextSnapshot(
            country_code=normalized_country,
            event_id=event_id,
            availability=availability,
            indicators=tuple(indicators),
            operational_presence=tuple(presence),
            retrieved_at=now,
            gaps=tuple(gaps),
            limitations=(
                "Displacement context is not causally attributed to the selected event "
                "unless the source explicitly says so.",
                "Operational presence is coordination context, not endorsement or "
                "proof of complete coverage.",
                "Baseline population and food-security values are contextual datasets, "
                "not observed event impacts.",
            ),
        )

    @staticmethod
    def _classify_freshness(
        records: tuple[HumanitarianIndicator, ...], *, now: datetime
    ) -> tuple[HumanitarianIndicator, ...]:
        return tuple(
            replace(
                item,
                stale=now - item.dataset_updated_at > _MAXIMUM_AGES[item.kind],
            )
            for item in records
        )
