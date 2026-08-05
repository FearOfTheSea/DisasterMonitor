"""Adapters for Japan Meteorological Agency JSON earthquake and tsunami feeds."""

import re
from datetime import datetime, timedelta

import httpx

from disaster_monitor.application.disaster import (
    DisasterEvent,
    DisasterQuery,
    FactStatus,
    ProviderBatch,
    ReportedFact,
    SituationReport,
    SourceReference,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import get_json

JMA_EARTHQUAKE_LIST_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"
JMA_TSUNAMI_LIST_URL = "https://www.jma.go.jp/bosai/tsunami/data/list.json"
JMA_DATA_BASE_URL = "https://www.jma.go.jp/bosai/quake/data/"
JMA_TSUNAMI_DATA_BASE_URL = "https://www.jma.go.jp/bosai/tsunami/data/"
_JMA_CODE = re.compile(
    r"(?P<lat>[+-]\d+(?:\.\d+)?)(?P<lon>[+-]\d+(?:\.\d+)?)-(?P<depth>\d+)"
)


def _parse_jma_code(value: object) -> tuple[float | None, float | None, float | None]:
    if not isinstance(value, str):
        return None, None, None
    match = _JMA_CODE.search(value)
    if not match:
        return None, None, None
    return (
        float(match.group("lat")),
        float(match.group("lon")),
        float(match.group("depth")) / 1_000,
    )


def _is_japan(latitude: float | None, longitude: float | None) -> bool:
    return (
        latitude is not None
        and longitude is not None
        and 20 <= latitude <= 46
        and 122 <= longitude <= 154
    )


def _safe_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


class JmaEarthquakeAdapter:
    """Identify recent Japanese earthquakes from the official JMA JSON list."""

    provider_name = "JMA"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        payload = await get_json(
            self._client,
            JMA_EARTHQUAKE_LIST_URL,
            max_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, list):
            raise DisasterProviderResponseError(
                "The JMA earthquake response was not a list."
            )
        events: list[DisasterEvent] = []
        start = now - timedelta(days=query.time_window_days)
        for item in payload[:200]:
            if not isinstance(item, dict):
                continue
            event_time = normalize_timestamp(item.get("at"))
            latitude, longitude, depth_km = _parse_jma_code(item.get("cod"))
            event_id = _safe_string(item.get("eid"))
            if not event_id or event_time is None or not _is_japan(latitude, longitude):
                continue
            if not start <= event_time <= now + timedelta(minutes=5):
                continue
            location = _safe_string(item.get("en_anm")) or _safe_string(item.get("anm"))
            published_at = normalize_timestamp(item.get("rdt")) or event_time
            detail_name = _safe_string(item.get("json"))
            source = SourceReference(
                publisher="Japan Meteorological Agency",
                title=(
                    f"{_safe_string(item.get('en_ttl')) or 'Earthquake information'}"
                    f" — {location or 'Japan'}"
                ),
                canonical_url=f"{JMA_DATA_BASE_URL}{detail_name}"
                if detail_name
                else JMA_EARTHQUAKE_LIST_URL,
                published_at=published_at,
                updated_at=published_at,
                retrieved_at=now,
            )
            magnitude = None
            try:
                magnitude = float(item["mag"])
            except (KeyError, TypeError, ValueError):
                pass
            intensity = _safe_string(item.get("maxi")) or None
            events.append(
                DisasterEvent(
                    event_id=f"jma:{event_id}",
                    hazard="earthquake",
                    location=location or "Japan",
                    country="Japan",
                    event_time=event_time,
                    source=source,
                    latitude=latitude,
                    longitude=longitude,
                    magnitude=magnitude,
                    magnitude_type=None,
                    intensity=f"JMA {intensity}" if intensity else None,
                    depth_km=depth_km,
                    significance=(magnitude or 0) * 100,
                    is_aftershock="aftershock" in location.lower(),
                )
            )
        return ProviderBatch(records=tuple(events))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class JmaTsunamiSituationAdapter:
    """Retrieve official tsunami status messages related to a selected event."""

    provider_name = "JMA tsunami"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        payload = await get_json(
            self._client,
            JMA_TSUNAMI_LIST_URL,
            max_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, list):
            raise DisasterProviderResponseError(
                "The JMA tsunami response was not a list."
            )
        raw_event_id = event.event_id.removeprefix("jma:")
        reports: list[SituationReport] = []
        for item in payload[:200]:
            if (
                not isinstance(item, dict)
                or _safe_string(item.get("eid")) != raw_event_id
            ):
                continue
            published_at = normalize_timestamp(item.get("rdt"))
            detail_name = _safe_string(item.get("json"))
            source = SourceReference(
                publisher="Japan Meteorological Agency",
                title=_safe_string(item.get("en_ttl")) or "Tsunami information",
                canonical_url=(
                    f"{JMA_TSUNAMI_DATA_BASE_URL}{detail_name}"
                    if detail_name
                    else JMA_TSUNAMI_LIST_URL
                ),
                published_at=published_at,
                updated_at=published_at,
                retrieved_at=now,
            )
            kinds = item.get("kind")
            labels = []
            if isinstance(kinds, list):
                for kind in kinds:
                    if isinstance(kind, dict) and _safe_string(kind.get("kind")):
                        labels.append(_safe_string(kind.get("kind")))
            value = ", ".join(labels) or "Tsunami status message published"
            reports.append(
                SituationReport(
                    source=source,
                    narrative=(
                        f"{_safe_string(item.get('en_ttl'))} — "
                        f"{_safe_string(item.get('en_anm'))}"
                    ).strip(" —"),
                    facts=(
                        ReportedFact(
                            category="tsunami",
                            label="Tsunami status",
                            value=value,
                            status=FactStatus.CONFIRMED,
                            source=source,
                            event_id=event.event_id,
                            observed_at=published_at,
                            claim_id="tsunami-status",
                        ),
                    ),
                    event_id=event.event_id,
                )
            )
        return ProviderBatch(records=tuple(reports))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
