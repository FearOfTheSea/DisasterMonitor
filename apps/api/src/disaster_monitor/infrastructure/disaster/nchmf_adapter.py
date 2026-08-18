"""Official Vietnam NCHMF RSS warning adapter for bounded hazard coverage."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from xml.etree.ElementTree import ParseError

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.services.operational_ingestion import (
    canonical_request_identity,
)
from disaster_monitor.domain.disaster import (
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

NCHMF_FEEDS = {
    Hazard.FLOOD: "https://nchmf.gov.vn/kttvsite/rss/lu-ngap-lut-16.rss",
    Hazard.LANDSLIDE: "https://nchmf.gov.vn/kttvsite/rss/lu-quet-17.rss",
    Hazard.TROPICAL_CYCLONE: (
        "https://nchmf.gov.vn/kttvsite/rss/bao-ap-thap-nhiet-doi-2049.rss"
    ),
}


@dataclass(frozen=True, slots=True)
class _RssItem:
    title: str
    published_at: datetime
    event_id: str
    snapshot_id: str | None


class NchmfWarningAdapter:
    """Read official warning headlines without treating them as impact facts."""

    provider_name = "NCHMF Vietnam warnings"
    source_id = "nchmf-vietnam-warnings"
    allowed_hosts = frozenset({"nchmf.gov.vn"})

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        items, issues = await self._items(query, now=now)
        return ProviderBatch(
            records=tuple(self._event(item, query, now=now) for item in items),
            issues=issues,
        )

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        items, issues = await self._items(query, now=now)
        reports: list[SituationReport] = []
        for item in items:
            candidate = self._event(item, query, now=now)
            if not event.has_provider_id(candidate.event_id):
                continue
            fact = ReportedFact(
                category="official_warning",
                label="NCHMF official warning bulletin",
                value=item.title,
                status=FactStatus.CONFIRMED,
                source=candidate.source,
                event_id=candidate.event_id,
                observed_at=item.published_at,
                claim_id=f"nchmf-warning:{item.event_id}",
            )
            reports.append(
                SituationReport(
                    source=candidate.source,
                    narrative=(
                        "NCHMF published this official warning headline. "
                        "No unreported impact total is inferred from the headline: "
                        f"{item.title}"
                    ),
                    facts=(fact,),
                    event_id=candidate.event_id,
                    reported_event_time=item.published_at,
                    locations=(candidate.location,),
                    countries=(query.country.canonical_name,),
                    country_codes=(query.country.alpha3_code,),
                    hazard=query.hazard,
                    provider_event_ids=(candidate.event_id,),
                )
            )
        return ProviderBatch(tuple(reports), issues)

    async def _items(
        self, query: DisasterQuery, *, now: datetime
    ) -> tuple[tuple[_RssItem, ...], tuple[ProviderIssue, ...]]:
        url = NCHMF_FEEDS.get(query.hazard)
        if url is None:
            return (), ()
        capture = (
            SnapshotCapture(
                self.source_id,
                canonical_request_identity(
                    self.source_id,
                    {"hazard": query.hazard.value, "version": "v1"},
                ),
                "nchmf-rss-terms-2026-08",
                now,
                self._snapshot_recorder,
            )
            if self._snapshot_recorder is not None
            else None
        )
        document = await get_text(
            self._client,
            url,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        try:
            root = ElementTree.fromstring(document)
        except (ParseError, DefusedXmlException) as error:
            raise DisasterProviderResponseError(
                "The NCHMF RSS response was malformed.",
                reason_code="malformed_xml",
            ) from error
        start = query.date_from or now - timedelta(days=query.time_window_days)
        end = query.date_to or now
        items: list[_RssItem] = []
        issues: list[ProviderIssue] = []
        for index, element in enumerate(root.findall("./channel/item")[:100]):
            title = (element.findtext("title") or "").strip()
            raw_date = (element.findtext("pubDate") or "").strip()
            try:
                published = parsedate_to_datetime(raw_date).astimezone(UTC)
            except (TypeError, ValueError, OverflowError):
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "NCHMF: A warning item with invalid time was skipped.",
                        reason_code="invalid_record",
                        detail=f"item[{index}]",
                    )
                )
                continue
            if not title or not start <= published <= end:
                continue
            material = (
                f"{query.hazard.value}|{published.isoformat()}|{title.casefold()}"
            )
            event_id = "nchmf:" + sha256(material.encode()).hexdigest()[:24]
            items.append(
                _RssItem(
                    title,
                    published,
                    event_id,
                    capture.snapshot.snapshot_id
                    if capture and capture.snapshot
                    else None,
                )
            )
        return (
            tuple(
                sorted(
                    items,
                    key=lambda item: (item.published_at, item.event_id),
                    reverse=True,
                )
            ),
            tuple(issues),
        )

    def _event(
        self, item: _RssItem, query: DisasterQuery, *, now: datetime
    ) -> DisasterEvent:
        url = NCHMF_FEEDS[query.hazard]
        source = SourceReference(
            source_id=self.source_id,
            publisher="Vietnam National Center for Hydro-Meteorological Forecasting",
            title=item.title,
            canonical_url=url,
            published_at=item.published_at,
            updated_at=None,
            retrieved_at=now,
            authority=SourceAuthority.NATIONAL_AUTHORITY,
            snapshot_id=item.snapshot_id,
        )
        return DisasterEvent(
            event_id=item.event_id,
            hazard=query.hazard,
            location=item.title[:240],
            country=query.country,
            event_time=item.published_at,
            source=source,
            provider_ids=(item.event_id,),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
