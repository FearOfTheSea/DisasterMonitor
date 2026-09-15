"""Bounded HDX HAPI v2 indicators and operational-presence adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import httpx

from disaster_monitor.domain.humanitarian import (
    HumanitarianIndicator,
    HumanitarianIndicatorKind,
    OperationalPresence,
)

_BASE_URL = "https://hapi.humdata.org/api/v2"
_INDICATOR_ENDPOINTS = (
    (
        "geography-infrastructure/baseline-population",
        HumanitarianIndicatorKind.BASELINE_POPULATION,
        "population",
    ),
    (
        "affected-people/internally-displaced-persons",
        HumanitarianIndicatorKind.DISPLACED_PEOPLE,
        "population",
    ),
    (
        "food-security-nutrition-poverty/food-security",
        HumanitarianIndicatorKind.FOOD_INSECURITY,
        "population_in_phase",
    ),
)


class HdxHapiContextAdapter:
    source_id = "hdx-hapi-context"

    def __init__(
        self,
        *,
        app_identifier: str | None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        maximum_response_bytes: int = 2_000_000,
    ) -> None:
        self._app_identifier = (app_identifier or "").strip()
        self._client = client or httpx.AsyncClient(timeout=15)
        self._owns_client = client is None
        self._clock = clock
        self._maximum_response_bytes = maximum_response_bytes

    @property
    def configured(self) -> bool:
        return bool(self._app_identifier)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def indicators(self, country_code: str) -> tuple[HumanitarianIndicator, ...]:
        if not self.configured:
            return ()
        country = _country(country_code)
        results = await asyncio.gather(
            *(
                self._get_rows(endpoint, country=country)
                for endpoint, _, _ in _INDICATOR_ENDPOINTS
            )
        )
        records: list[HumanitarianIndicator] = []
        for (_, kind, value_field), rows in zip(
            _INDICATOR_ENDPOINTS, results, strict=True
        ):
            records.extend(
                item
                for row in rows
                if (item := self._indicator(row, kind, value_field, country))
                is not None
            )
        return tuple(
            sorted(records, key=lambda item: (item.kind.value, item.indicator_id))
        )

    async def operational_presence(
        self, country_code: str
    ) -> tuple[OperationalPresence, ...]:
        if not self.configured:
            return ()
        country = _country(country_code)
        rows = await self._get_rows(
            "coordination-context/operational-presence", country=country
        )
        records = (
            item for row in rows if (item := self._presence(row, country)) is not None
        )
        return tuple(
            sorted(records, key=lambda item: (item.organization, item.presence_id))
        )

    async def _get_rows(
        self, endpoint: str, *, country: str
    ) -> tuple[dict[str, Any], ...]:
        response = await self._client.get(
            f"{_BASE_URL}/{endpoint}",
            params={
                "location_code": country,
                "admin_level": 0,
                "output_format": "json",
                "offset": 0,
                "limit": 1_000,
                "app_identifier": self._app_identifier,
            },
            follow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > self._maximum_response_bytes:
            raise ValueError("HDX HAPI response exceeds the byte limit.")
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("HDX HAPI response has no record list.")
        return tuple(row for row in rows if isinstance(row, dict))

    def _indicator(
        self,
        row: dict[str, Any],
        kind: HumanitarianIndicatorKind,
        value_field: str,
        country: str,
    ) -> HumanitarianIndicator | None:
        try:
            if str(row.get("location_code") or "").upper() != country:
                return None
            if kind is HumanitarianIndicatorKind.BASELINE_POPULATION and (
                str(row.get("gender") or "all").casefold() != "all"
                or str(row.get("age_range") or "all").casefold() != "all"
            ):
                return None
            license_name = _required(row, "dataset_hdx_license")
            reference_start = _timestamp(_required(row, "reference_period_start"))
            reference_end = _timestamp(_required(row, "reference_period_end"))
            dataset_id = _required(row, "resource_hdx_id")
            source_url = _source_url(row)
            dimensions = tuple(
                (key, str(row[key]))
                for key in (
                    "operation",
                    "reporting_round",
                    "ipc_phase",
                    "ipc_type",
                )
                if row.get(key) not in {None, ""}
            )
            identity = sha256(
                f"{kind.value}|{dataset_id}|{row.get('admin1_code')}|{dimensions}".encode()
            ).hexdigest()[:24]
            return HumanitarianIndicator(
                indicator_id=f"hdx-hapi:{identity}",
                source_id=self.source_id,
                kind=kind,
                value=float(row[value_field]),
                unit="people",
                country_code=country,
                admin1_code=_optional(row, "admin1_code"),
                admin1_name=_optional(row, "admin1_name"),
                reference_period_start=reference_start,
                reference_period_end=reference_end,
                dataset_id=f"hdx:{dataset_id}",
                dataset_updated_at=_dataset_updated_at(row, reference_end),
                retrieved_at=self._clock(),
                source_url=source_url,
                license_name=license_name,
                causal_attribution=False,
                dimensions=dimensions,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _presence(
        self, row: dict[str, Any], country: str
    ) -> OperationalPresence | None:
        try:
            if str(row.get("location_code") or "").upper() != country:
                return None
            organization = _required(row, "org_name")
            sector = _required(row, "sector_name")
            dataset_id = _required(row, "resource_hdx_id")
            license_name = _required(row, "dataset_hdx_license")
            reference_end = _timestamp(_required(row, "reference_period_end"))
            identity = sha256(
                f"{dataset_id}|{organization}|{sector}|{row.get('admin1_code')}".encode()
            ).hexdigest()[:24]
            return OperationalPresence(
                presence_id=f"hdx-presence:{identity}",
                source_id=self.source_id,
                organization=organization,
                acronym=_optional(row, "org_acronym"),
                sector=sector,
                country_code=country,
                admin1_code=_optional(row, "admin1_code"),
                admin1_name=_optional(row, "admin1_name"),
                dataset_id=f"hdx:{dataset_id}",
                dataset_updated_at=_dataset_updated_at(row, reference_end),
                retrieved_at=self._clock(),
                source_url=_source_url(row),
                license_name=license_name,
            )
        except (TypeError, ValueError):
            return None


def _country(value: str) -> str:
    result = value.strip().upper()
    if len(result) != 3 or not result.isalpha():
        raise ValueError("HDX HAPI requires an ISO alpha-3 country code.")
    return result


def _required(row: dict[str, Any], key: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise ValueError(f"HDX HAPI record is missing {key}.")
    return value


def _optional(row: dict[str, Any], key: str) -> str | None:
    value = str(row.get(key) or "").strip()
    return value or None


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _dataset_updated_at(row: dict[str, Any], fallback: datetime) -> datetime:
    value = _optional(row, "dataset_hdx_modified_date")
    return _timestamp(value) if value else fallback


def _source_url(row: dict[str, Any]) -> str:
    stub = _optional(row, "dataset_hdx_stub")
    return (
        f"https://data.humdata.org/dataset/{stub}"
        if stub
        else "https://hapi.humdata.org/"
    )
