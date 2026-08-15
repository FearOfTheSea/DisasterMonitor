"""Configured Copernicus GFM notification adapter for Vietnam flood analysis."""

import re
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
)
from disaster_monitor.application.services.operational_ingestion import (
    canonical_request_identity,
)
from disaster_monitor.domain.disaster import (
    CorrelationStatus,
    DisasterEvent,
    FactStatus,
    Hazard,
    ReportedFact,
    SituationReport,
    SourceAuthority,
    SourceReference,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    SnapshotCapture,
    SourcePayloadRecorder,
    get_json,
)

GFM_API_ROOT = "https://api.gfm.eodc.eu/v2"


class GfmFloodNotificationAdapter:
    """Expose satellite flood-product availability as analytical evidence."""

    provider_name = "Copernicus GFM Vietnam notifications"
    source_id = "copernicus-gfm-vietnam"
    allowed_hosts = frozenset({"api.gfm.eodc.eu"})

    def __init__(
        self,
        *,
        access_token: str | None,
        user_id: str | None,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._access_token = (access_token or "").strip()
        self._user_id = (user_id or "").strip()
        if self._user_id and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", self._user_id):
            raise ValueError("GFM user ID contains unsupported characters.")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    @property
    def configured(self) -> bool:
        return bool(self._access_token and self._user_id)

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if not self.configured or query.hazard != Hazard.FLOOD:
            return ProviderBatch()
        capture = (
            SnapshotCapture(
                self.source_id,
                canonical_request_identity(
                    self.source_id,
                    {
                        "country": query.country.alpha3_code,
                        "scope": "notifications",
                    },
                ),
                "copernicus-gfm-terms-2026-08",
                now,
                self._snapshot_recorder,
            )
            if self._snapshot_recorder is not None
            else None
        )
        payload = await get_json(
            self._client,
            f"{GFM_API_ROOT}/notifications/push_notifications/{self._user_id}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("push_notifications"), list
        ):
            raise DisasterProviderResponseError(
                "The GFM notification response had an unsupported schema.",
                reason_code="invalid_schema",
            )
        start = query.date_from or now - timedelta(days=query.time_window_days)
        end = query.date_to or now
        events: list[DisasterEvent] = []
        issues: list[ProviderIssue] = []
        for index, raw in enumerate(payload["push_notifications"][:500]):
            if not isinstance(raw, dict):
                issues.append(_issue(index))
                continue
            product_id = _text(raw.get("product_id"))
            aoi_id = _text(raw.get("aoi_id"))
            product_time = normalize_timestamp(raw.get("product_time"))
            if not product_id or not aoi_id or product_time is None:
                issues.append(_issue(index))
                continue
            if not start <= product_time <= end:
                continue
            location = (
                _text(raw.get("aoi_name")) or "Configured Vietnam area of interest"
            )
            event_id = f"gfm:{aoi_id}:{product_id}"
            source = SourceReference(
                source_id=self.source_id,
                publisher="Copernicus Emergency Management Service",
                title="Global Flood Monitoring satellite product",
                canonical_url=f"{GFM_API_ROOT}/products/{quote(product_id, safe='')}",
                published_at=product_time,
                updated_at=None,
                retrieved_at=now,
                authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
                snapshot_id=(
                    capture.snapshot.snapshot_id
                    if capture and capture.snapshot
                    else None
                ),
            )
            events.append(
                DisasterEvent(
                    event_id=event_id,
                    hazard=Hazard.FLOOD,
                    location=location,
                    country=query.country,
                    event_time=product_time,
                    source=source,
                    provider_ids=(event_id,),
                )
            )
        return ProviderBatch(
            tuple(
                sorted(
                    events,
                    key=lambda item: (item.event_time, item.event_id),
                    reverse=True,
                )
            ),
            tuple(issues),
        )

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        batch = await self.find_recent_events(query, now=now)
        reports = tuple(
            SituationReport(
                source=item.source,
                narrative=(
                    "Copernicus GFM made a satellite-derived flood-monitoring product "
                    "available for the configured area of interest. This analytical "
                    "product is not a national warning."
                ),
                facts=(
                    ReportedFact(
                        category="analytical_flood_product",
                        label="GFM satellite flood product",
                        value=f"Available for {item.location}",
                        status=FactStatus.ESTIMATED,
                        source=item.source,
                        event_id=item.event_id,
                        observed_at=item.event_time,
                    ),
                ),
                event_id=item.event_id,
                correlation=CorrelationStatus.MATCHED,
                reported_event_time=item.event_time,
                locations=(item.location,),
                countries=(query.country.canonical_name,),
                country_codes=(query.country.alpha3_code,),
                hazard=Hazard.FLOOD,
                provider_event_ids=(item.event_id,),
            )
            for item in batch.records
            if event.has_provider_id(item.event_id)
        )
        return ProviderBatch(reports, batch.issues)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _issue(index: int) -> ProviderIssue:
    return ProviderIssue(
        GfmFloodNotificationAdapter.provider_name,
        "Copernicus GFM: A malformed notification was skipped.",
        reason_code="invalid_record",
        detail=f"push_notifications[{index}]",
    )
