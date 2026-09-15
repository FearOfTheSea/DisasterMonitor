"""Configurable IOM DTM v3 public aggregated displacement adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import httpx

from disaster_monitor.domain.humanitarian import (
    HumanitarianIndicator,
    HumanitarianIndicatorKind,
)


class IomDtmContextAdapter:
    source_id = "iom-dtm-displacement"

    def __init__(
        self,
        *,
        api_url: str | None,
        subscription_key: str | None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        maximum_response_bytes: int = 2_000_000,
    ) -> None:
        self._api_url = (api_url or "").strip()
        self._subscription_key = (subscription_key or "").strip()
        if self._api_url:
            parsed = urlparse(self._api_url)
            if parsed.scheme != "https" or parsed.hostname != "api.dtm.iom.int":
                raise ValueError("IOM DTM API URL must use the approved HTTPS host.")
        self._client = client or httpx.AsyncClient(timeout=15)
        self._owns_client = client is None
        self._clock = clock
        self._maximum_response_bytes = maximum_response_bytes

    @property
    def configured(self) -> bool:
        return bool(self._api_url and self._subscription_key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def indicators(self, country_code: str) -> tuple[HumanitarianIndicator, ...]:
        if not self.configured:
            return ()
        country = country_code.strip().upper()
        if len(country) != 3 or not country.isalpha():
            raise ValueError("IOM DTM requires an ISO alpha-3 country code.")
        response = await self._client.get(
            self._api_url,
            params={"countryCode": country, "limit": 1_000},
            headers={"Ocp-Apim-Subscription-Key": self._subscription_key},
            follow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > self._maximum_response_bytes:
            raise ValueError("IOM DTM response exceeds the byte limit.")
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("IOM DTM response has no data list.")
        records = (
            item
            for row in rows
            if isinstance(row, dict)
            and (item := self._record(row, country)) is not None
        )
        return tuple(sorted(records, key=lambda item: item.indicator_id))

    def _record(
        self, row: dict[str, Any], country: str
    ) -> HumanitarianIndicator | None:
        try:
            if str(row.get("countryCode") or "").upper() != country:
                return None
            row_id = _required(row, "id")
            source_url = _required(row, "datasetUrl")
            if not source_url.startswith("https://dtm.iom.int/"):
                return None
            reporting_at = _timestamp(_required(row, "reportingDate"))
            license_name = _required(row, "license")
            round_value = str(row.get("round") or "unknown")
            identity = sha256(f"{row_id}|{round_value}".encode()).hexdigest()[:24]
            return HumanitarianIndicator(
                indicator_id=f"iom-dtm:{identity}",
                source_id=self.source_id,
                kind=HumanitarianIndicatorKind.DISPLACED_PEOPLE,
                value=float(row["individuals"]),
                unit="people",
                country_code=country,
                admin1_code=_optional(row, "admin1Code"),
                admin1_name=_optional(row, "admin1Name"),
                reference_period_start=reporting_at,
                reference_period_end=reporting_at,
                dataset_id=f"iom-dtm:{row_id}",
                dataset_updated_at=reporting_at,
                retrieved_at=self._clock(),
                source_url=source_url,
                license_name=license_name,
                causal_attribution=False,
                dimensions=(("round", round_value),),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _required(row: dict[str, Any], key: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise ValueError(f"IOM DTM record is missing {key}.")
    return value


def _optional(row: dict[str, Any], key: str) -> str | None:
    value = str(row.get(key) or "").strip()
    return value or None


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
