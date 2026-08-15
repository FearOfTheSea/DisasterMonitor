"""NASA FIRMS active-fire observation adapter with bounded country queries."""

import csv
import io
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.ports.geography import CountryCatalog
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
    get_text,
)

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_PUBLIC_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/"
FIRMS_SOURCES = frozenset(
    {
        "MODIS_NRT",
        "VIIRS_NOAA20_NRT",
        "VIIRS_NOAA21_NRT",
        "VIIRS_SNPP_NRT",
    }
)


class FirmsActiveFireAdapter:
    """Represent satellite detections as observations, never incident declarations."""

    provider_name = "NASA FIRMS active fire"
    source_id = "nasa-firms-active-fire"
    allowed_hosts = frozenset({"firms.modaps.eosdis.nasa.gov"})

    def __init__(
        self,
        *,
        geography: CountryCatalog,
        map_key: str | None,
        dataset: str = "VIIRS_NOAA20_NRT",
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 5_000_000,
    ) -> None:
        key = (map_key or "").strip()
        if key and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            raise ValueError("FIRMS map key contains unsupported characters.")
        if dataset not in FIRMS_SOURCES:
            raise ValueError("FIRMS dataset is outside the reviewed NRT allowlist.")
        self._geography = geography
        self._map_key = key
        self._dataset = dataset
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    @property
    def configured(self) -> bool:
        return bool(self._map_key)

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if not self.configured or query.hazard != Hazard.WILDFIRE:
            return ProviderBatch()
        capture = (
            SnapshotCapture(
                self.source_id,
                canonical_request_identity(
                    self.source_id,
                    {
                        "country": query.country.alpha3_code,
                        "dataset": self._dataset,
                        "days": str(min(10, max(1, query.time_window_days))),
                    },
                ),
                "nasa-firms-api-terms-2026-08",
                now,
                self._snapshot_recorder,
            )
            if self._snapshot_recorder is not None
            else None
        )
        text = await get_text(
            self._client,
            self._url(query),
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        records, issues = self._parse(
            text,
            query,
            now=now,
            snapshot_id=capture.snapshot.snapshot_id
            if capture and capture.snapshot
            else None,
        )
        return ProviderBatch(records, issues)

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        batch = await self.find_recent_events(query, now=now)
        reports: list[SituationReport] = []
        for candidate in batch.records:
            if not event.has_provider_id(candidate.event_id):
                continue
            confidence = candidate.intensity or "reported confidence unavailable"
            facts = (
                ReportedFact(
                    category="satellite_observation",
                    label="NASA FIRMS active-fire detection",
                    value=confidence,
                    status=FactStatus.CONFIRMED,
                    source=candidate.source,
                    event_id=candidate.event_id,
                    observed_at=candidate.event_time,
                ),
            )
            reports.append(
                SituationReport(
                    source=candidate.source,
                    narrative=(
                        "NASA FIRMS reported a satellite-derived active-fire "
                        "detection. "
                        "This is not an official wildfire incident declaration."
                    ),
                    facts=facts,
                    event_id=candidate.event_id,
                    correlation=CorrelationStatus.MATCHED,
                    reported_event_time=candidate.event_time,
                    locations=(candidate.location,),
                    countries=(query.country.canonical_name,),
                    country_codes=(query.country.alpha3_code,),
                    hazard=Hazard.WILDFIRE,
                    provider_event_ids=(candidate.event_id,),
                )
            )
        return ProviderBatch(tuple(reports), batch.issues)

    def _url(self, query: DisasterQuery) -> str:
        area = query.country.geographic_area
        coordinates = ",".join(
            str(value)
            for value in (
                area.min_longitude,
                area.min_latitude,
                area.max_longitude,
                area.max_latitude,
            )
        )
        day_range = min(10, max(1, query.time_window_days))
        return (
            f"{FIRMS_BASE_URL}/{self._map_key}/{self._dataset}/"
            f"{coordinates}/{day_range}"
        )

    def _parse(
        self,
        document: str,
        query: DisasterQuery,
        *,
        now: datetime,
        snapshot_id: str | None,
    ) -> tuple[tuple[DisasterEvent, ...], tuple[ProviderIssue, ...]]:
        reader = csv.DictReader(io.StringIO(document))
        required = {"latitude", "longitude", "acq_date", "acq_time"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise DisasterProviderResponseError(
                "The FIRMS response did not contain the required CSV fields.",
                reason_code="invalid_schema",
            )
        start = query.date_from or now - timedelta(days=query.time_window_days)
        end = query.date_to or now
        events: list[DisasterEvent] = []
        issues: list[ProviderIssue] = []
        for index, row in enumerate(reader):
            if index >= 5_000:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "NASA FIRMS: Additional detections were truncated.",
                        reason_code="result_limit",
                    )
                )
                break
            try:
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
                clock = str(row["acq_time"]).strip().zfill(4)
                event_time = datetime.strptime(
                    f"{row['acq_date']} {clock}", "%Y-%m-%d %H%M"
                ).replace(tzinfo=UTC)
            except (KeyError, TypeError, ValueError, OverflowError):
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "NASA FIRMS: A malformed detection was skipped.",
                        reason_code="invalid_record",
                        detail=f"row[{index}]",
                    )
                )
                continue
            if not start <= event_time <= end or not self._geography.contains(
                query.country, latitude, longitude
            ):
                continue
            material = "|".join(
                (
                    self._dataset,
                    f"{latitude:.5f}",
                    f"{longitude:.5f}",
                    event_time.isoformat(),
                    str(row.get("satellite", "")),
                )
            )
            event_id = "firms:" + sha256(material.encode()).hexdigest()[:24]
            confidence = str(row.get("confidence", "")).strip()
            frp = _float(row.get("frp"))
            source = SourceReference(
                source_id=self.source_id,
                publisher="NASA Fire Information for Resource Management System",
                title="Satellite-derived active-fire detection",
                canonical_url=FIRMS_PUBLIC_URL,
                published_at=event_time,
                updated_at=None,
                retrieved_at=now,
                authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
                snapshot_id=snapshot_id,
            )
            events.append(
                DisasterEvent(
                    event_id=event_id,
                    hazard=Hazard.WILDFIRE,
                    location=(
                        f"Satellite active-fire detection in "
                        f"{query.country.canonical_name}"
                    ),
                    country=query.country,
                    event_time=event_time,
                    source=source,
                    latitude=latitude,
                    longitude=longitude,
                    intensity=f"FIRMS confidence {confidence}" if confidence else None,
                    significance=frp,
                    provider_ids=(event_id,),
                )
            )
        return (
            tuple(
                sorted(
                    events,
                    key=lambda item: (item.event_time, item.event_id),
                    reverse=True,
                )
            ),
            tuple(issues),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _float(value: object) -> float | None:
    try:
        return float(str(value)) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None
