"""Fail-closed reader for normalized DesInventar or DELTA CSV exports."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from disaster_monitor.application.ports.historical_loss import HistoricalLossProvider
from disaster_monitor.domain.disaster_types import Disaster, _is_aware
from disaster_monitor.domain.historical_loss import HistoricalLossRecord

_REQUIRED_COLUMNS = frozenset(
    {
        "record_id",
        "country_code",
        "hazard",
        "event_name",
        "occurred_at",
        "fatalities",
        "people_affected",
        "economic_loss_usd",
    }
)


class ReviewedHistoricalLossCsvAdapter(HistoricalLossProvider):
    def __init__(
        self,
        *,
        source_id: str,
        dataset_id: str,
        source_url: str,
        license_name: str,
        dataset_updated_at: datetime,
        retrieved_at: datetime,
        content: str,
    ) -> None:
        if not source_id.startswith(("desinventar-", "delta-")):
            raise ValueError("Historical CSV source must be DesInventar or DELTA.")
        if not dataset_id.strip():
            raise ValueError("Historical CSV requires a dataset ID.")
        if not source_url.startswith("https://"):
            raise ValueError("Historical CSV requires an HTTPS source URL.")
        if not license_name.strip():
            raise ValueError("Historical CSV requires reviewed license terms.")
        if not _is_aware(dataset_updated_at) or not _is_aware(retrieved_at):
            raise ValueError("Historical CSV timestamps must be timezone-aware.")
        self.source_id = source_id
        self._dataset_id = dataset_id
        self._source_url = source_url
        self._license_name = license_name
        self._dataset_updated_at = dataset_updated_at
        self._retrieved_at = retrieved_at
        self._records = self._parse(content)

    async def records(
        self, *, country_code: str, hazard: Disaster
    ) -> tuple[HistoricalLossRecord, ...]:
        normalized_country = country_code.strip().upper()
        return tuple(
            record
            for record in self._records
            if record.country_code == normalized_country and record.hazard is hazard
        )

    def _parse(self, content: str) -> tuple[HistoricalLossRecord, ...]:
        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None or not _REQUIRED_COLUMNS <= set(reader.fieldnames):
            raise ValueError("Historical CSV is missing required columns.")
        records = []
        for index, row in enumerate(reader, start=2):
            try:
                hazard = Disaster(row["hazard"].strip())
            except (KeyError, ValueError) as error:
                raise ValueError(
                    f"Historical CSV row {index} has an unsupported hazard."
                ) from error
            try:
                records.append(
                    HistoricalLossRecord(
                        record_id=f"{self.source_id}:{row['record_id'].strip()}",
                        dataset_id=self._dataset_id,
                        source_id=self.source_id,
                        country_code=row["country_code"].strip().upper(),
                        hazard=hazard,
                        event_name=row["event_name"].strip(),
                        occurred_at=_datetime(row["occurred_at"]),
                        fatalities=_integer(row["fatalities"]),
                        people_affected=_integer(row["people_affected"]),
                        economic_loss_usd=_number(row["economic_loss_usd"]),
                        source_url=self._source_url,
                        license_name=self._license_name,
                        dataset_updated_at=self._dataset_updated_at,
                        retrieved_at=self._retrieved_at,
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Historical CSV row {index} is invalid.") from error
        return tuple(records)


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if not _is_aware(parsed):
        raise ValueError("Historical occurrence time must be timezone-aware.")
    return parsed


def _integer(value: str) -> int | None:
    stripped = value.strip()
    return int(stripped) if stripped else None


def _number(value: str) -> float | None:
    stripped = value.strip()
    return float(stripped) if stripped else None


__all__ = ["ReviewedHistoricalLossCsvAdapter"]
