from datetime import UTC, datetime

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.infrastructure.historical_loss.reviewed_csv import (
    ReviewedHistoricalLossCsvAdapter,
)

NOW = datetime(2026, 9, 22, 8, tzinfo=UTC)


@pytest.mark.asyncio
async def test_reviewed_desinventar_csv_retains_license_and_historical_role() -> None:
    adapter = ReviewedHistoricalLossCsvAdapter(
        source_id="desinventar-reviewed-export",
        dataset_id="desinventar-vnm-2025",
        source_url="https://www.desinventar.net/database",
        license_name="reviewed dataset terms",
        dataset_updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        retrieved_at=NOW,
        content=(
            "record_id,country_code,hazard,event_name,occurred_at,fatalities,"
            "people_affected,economic_loss_usd\n"
            "1999-01,VNM,flood,1999 river flood,1999-11-01T00:00:00Z,12,"
            "50000,\n"
            "other,THA,flood,Other country,2000-01-01T00:00:00Z,1,100,\n"
        ),
    )

    records = await adapter.records(country_code="VNM", hazard=Disaster.FLOOD)

    assert len(records) == 1
    assert records[0].record_id == "desinventar-reviewed-export:1999-01"
    assert records[0].license_name == "reviewed dataset terms"
    assert records[0].role == "historical_preparedness_context"
    assert records[0].current_impact_inference is False


def test_reviewed_loss_csv_fails_closed_on_unknown_hazard_or_missing_terms() -> None:
    with pytest.raises(ValueError, match="license"):
        ReviewedHistoricalLossCsvAdapter(
            source_id="delta-reviewed-export",
            dataset_id="delta-v1",
            source_url="https://example.test/delta",
            license_name="",
            dataset_updated_at=NOW,
            retrieved_at=NOW,
            content=(
                "record_id,country_code,hazard,event_name,occurred_at,fatalities,"
                "people_affected,economic_loss_usd\n"
            ),
        )

    with pytest.raises(ValueError, match="hazard"):
        ReviewedHistoricalLossCsvAdapter(
            source_id="desinventar-reviewed-export",
            dataset_id="desinventar-v1",
            source_url="https://www.desinventar.net/database",
            license_name="reviewed terms",
            dataset_updated_at=NOW,
            retrieved_at=NOW,
            content=(
                "record_id,country_code,hazard,event_name,occurred_at,fatalities,"
                "people_affected,economic_loss_usd\n"
                "bad,VNM,meteor,Unknown,1999-01-01T00:00:00Z,,,,\n"
            ),
        )
