from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.humanitarian.context import (
    HumanitarianContextService,
)
from disaster_monitor.domain.humanitarian import (
    ContextAvailability,
    HumanitarianIndicator,
    HumanitarianIndicatorKind,
    OperationalPresence,
)

NOW = datetime(2026, 9, 16, 8, tzinfo=UTC)


class FakeIndicatorProvider:
    source_id = "fixture-humanitarian"

    def __init__(self, records: tuple[HumanitarianIndicator, ...]) -> None:
        self.records = records

    async def indicators(self, country_code: str) -> tuple[HumanitarianIndicator, ...]:
        assert country_code == "VNM"
        return self.records


class FakePresenceProvider:
    source_id = "fixture-presence"

    async def operational_presence(
        self, country_code: str
    ) -> tuple[OperationalPresence, ...]:
        assert country_code == "VNM"
        return (
            OperationalPresence(
                presence_id="presence:one",
                source_id=self.source_id,
                organization="Example Relief Organization",
                acronym="ERO",
                sector="Shelter",
                country_code="VNM",
                admin1_code="VN-01",
                admin1_name="Test Province",
                dataset_id="hdx:resource-1",
                dataset_updated_at=NOW - timedelta(days=10),
                retrieved_at=NOW,
                source_url="https://data.humdata.org/dataset/example",
                license_name="HDX dataset-specific license",
            ),
        )


def _indicator(
    kind: HumanitarianIndicatorKind,
    *,
    value: float,
    valid_at: datetime,
    causal_attribution: bool = False,
) -> HumanitarianIndicator:
    return HumanitarianIndicator(
        indicator_id=f"indicator:{kind.value}",
        source_id="fixture-humanitarian",
        kind=kind,
        value=value,
        unit="people",
        country_code="VNM",
        admin1_code=None,
        admin1_name=None,
        reference_period_start=valid_at,
        reference_period_end=valid_at,
        dataset_id=f"dataset:{kind.value}",
        dataset_updated_at=valid_at,
        retrieved_at=NOW,
        source_url="https://data.humdata.org/dataset/example",
        license_name="HDX dataset-specific license",
        causal_attribution=causal_attribution,
    )


@pytest.mark.asyncio
async def test_humanitarian_context_keeps_freshness_and_coordination_caveats() -> None:
    records = (
        _indicator(
            HumanitarianIndicatorKind.BASELINE_POPULATION,
            value=1_000_000,
            valid_at=NOW - timedelta(days=200),
        ),
        _indicator(
            HumanitarianIndicatorKind.DISPLACED_PEOPLE,
            value=5_000,
            valid_at=NOW - timedelta(days=20),
        ),
        _indicator(
            HumanitarianIndicatorKind.FOOD_INSECURITY,
            value=20_000,
            valid_at=NOW - timedelta(days=500),
        ),
    )
    result = await HumanitarianContextService(
        indicator_providers=(FakeIndicatorProvider(records),),
        presence_providers=(FakePresenceProvider(),),
        clock=lambda: NOW,
    ).for_country("vnm", event_id="event-1")

    assert result.availability is ContextAvailability.PARTIAL
    assert [item.kind for item in result.indicators] == [
        HumanitarianIndicatorKind.BASELINE_POPULATION,
        HumanitarianIndicatorKind.DISPLACED_PEOPLE,
        HumanitarianIndicatorKind.FOOD_INSECURITY,
    ]
    assert result.indicators[2].stale is True
    assert result.indicators[1].causal_attribution is False
    assert result.operational_presence[0].organization == (
        "Example Relief Organization"
    )
    assert any("not endorsement" in item for item in result.limitations)
    assert any("not causally" in item for item in result.limitations)


@pytest.mark.asyncio
async def test_humanitarian_context_makes_no_data_and_provider_failure_explicit() -> (
    None
):
    class FailingProvider:
        source_id = "failed-source"

        async def indicators(
            self, country_code: str
        ) -> tuple[HumanitarianIndicator, ...]:
            raise RuntimeError("private upstream detail")

    result = await HumanitarianContextService(
        indicator_providers=(FailingProvider(),),
        clock=lambda: NOW,
    ).for_country("VNM", event_id="event-1")

    assert result.availability is ContextAvailability.UNAVAILABLE
    assert result.indicators == ()
    assert result.gaps == (
        "failed-source was unavailable; no absence can be inferred.",
    )
