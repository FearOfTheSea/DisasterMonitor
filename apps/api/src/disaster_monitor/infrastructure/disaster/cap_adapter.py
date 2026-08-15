"""Generic CAP 1.2 alert adapter requiring an explicitly reviewed authority."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from xml.etree.ElementTree import Element, ParseError

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

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
    get_text,
    validate_network_target,
)


@dataclass(frozen=True, slots=True)
class _CapRecord:
    identifier: str
    sender: str
    sent: datetime
    message_type: str
    event: str
    headline: str
    description: str
    instruction: str
    severity: str
    urgency: str
    certainty: str
    area_description: str
    latitude: float | None
    longitude: float | None
    canonical_url: str
    snapshot_id: str | None = None


class CapAlertAdapter:
    """Parse public/actual CAP messages under constructor-bound network authority."""

    def __init__(
        self,
        *,
        provider_name: str,
        source_id: str,
        publisher: str,
        feed_url: str,
        allowed_hosts: frozenset[str],
        rights_id: str,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        if not all(
            value.strip() for value in (provider_name, source_id, publisher, rights_id)
        ):
            raise ValueError("CAP authority registration requires stable identity.")
        validate_network_target(feed_url, allowed_hosts)
        self.provider_name = provider_name
        self.source_id = source_id
        self.allowed_hosts = allowed_hosts
        self._publisher = publisher
        self._feed_url = feed_url
        self._rights_id = rights_id
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_response_bytes = max_response_bytes
        self._snapshot_recorder = snapshot_recorder

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        records, issues = await self._records(query, now=now)
        events = tuple(self._event(item, query, now=now) for item in records)
        return ProviderBatch(events, issues)

    async def get_situation_reports(
        self,
        event: DisasterEvent,
        query: DisasterQuery,
        *,
        now: datetime,
    ) -> ProviderBatch[SituationReport]:
        records, issues = await self._records(query, now=now)
        reports: list[SituationReport] = []
        for record in records:
            candidate = self._event(record, query, now=now)
            if not event.has_provider_id(candidate.event_id):
                continue
            status_value = ", ".join(
                value
                for value in (
                    f"message={record.message_type}",
                    f"severity={record.severity}" if record.severity else "",
                    f"urgency={record.urgency}" if record.urgency else "",
                    f"certainty={record.certainty}" if record.certainty else "",
                )
                if value
            )
            facts = (
                ReportedFact(
                    category="official_warning",
                    label="CAP public alert status",
                    value=status_value,
                    status=FactStatus.CONFIRMED,
                    source=candidate.source,
                    event_id=candidate.event_id,
                    observed_at=record.sent,
                    claim_id=f"cap-warning:{record.identifier}",
                ),
            )
            narrative = record.description or record.headline or record.event
            if record.instruction:
                narrative += (
                    "\n\nSource-issued instruction (not a DisasterMonitor directive): "
                    + record.instruction
                )
            reports.append(
                SituationReport(
                    source=candidate.source,
                    narrative=narrative[:4_000],
                    facts=facts,
                    event_id=candidate.event_id,
                    correlation=CorrelationStatus.MATCHED,
                    reported_event_time=record.sent,
                    locations=(candidate.location,),
                    countries=(query.country.canonical_name,),
                    country_codes=(query.country.alpha3_code,),
                    hazard=query.hazard,
                    provider_event_ids=(candidate.event_id,),
                )
            )
        return ProviderBatch(tuple(reports), issues)

    async def _records(
        self, query: DisasterQuery, *, now: datetime
    ) -> tuple[tuple[_CapRecord, ...], tuple[ProviderIssue, ...]]:
        feed_capture = self._capture(query, now, "feed")
        document = await get_text(
            self._client,
            self._feed_url,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=feed_capture,
        )
        documents = [(self._feed_url, document, feed_capture)]
        root = _xml(document)
        if _local_name(root.tag) != "alert":
            documents = []
            for link in _feed_links(root)[:20]:
                try:
                    validate_network_target(link, self.allowed_hosts)
                    linked_capture = self._capture(query, now, link)
                    linked = await get_text(
                        self._client,
                        link,
                        allowed_hosts=self.allowed_hosts,
                        max_bytes=self._max_response_bytes,
                        provider_name=self.provider_name,
                        capture=linked_capture,
                    )
                except Exception:
                    continue
                documents.append((link, linked, linked_capture))
        start = query.date_from or now - timedelta(days=query.time_window_days)
        end = query.date_to or now
        records: list[_CapRecord] = []
        issues: list[ProviderIssue] = []
        for index, (url, content, capture) in enumerate(documents):
            try:
                record = _parse_cap(_xml(content), url)
            except DisasterProviderResponseError as error:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        f"{self.provider_name}: An invalid CAP alert was skipped.",
                        reason_code=error.failure.reason_code,
                        detail=f"document[{index}]",
                    )
                )
                continue
            if (
                record is not None
                and start <= record.sent <= end
                and _matches_hazard(record.event, query.hazard)
            ):
                records.append(
                    replace(
                        record,
                        snapshot_id=(
                            capture.snapshot.snapshot_id
                            if capture and capture.snapshot
                            else None
                        ),
                    )
                )
        return (
            tuple(
                sorted(
                    records, key=lambda item: (item.sent, item.identifier), reverse=True
                )
            ),
            tuple(issues),
        )

    def _capture(
        self, query: DisasterQuery, now: datetime, document: str
    ) -> SnapshotCapture | None:
        if self._snapshot_recorder is None:
            return None
        return SnapshotCapture(
            self.source_id,
            canonical_request_identity(
                self.source_id,
                {
                    "country": query.country.alpha3_code,
                    "hazard": query.hazard.value,
                    "document": document,
                },
            ),
            self._rights_id,
            now,
            self._snapshot_recorder,
        )

    def _event(
        self, record: _CapRecord, query: DisasterQuery, *, now: datetime
    ) -> DisasterEvent:
        source = SourceReference(
            source_id=self.source_id,
            publisher=self._publisher,
            title=record.headline or record.event,
            canonical_url=record.canonical_url,
            published_at=record.sent,
            updated_at=record.sent if record.message_type == "Update" else None,
            retrieved_at=now,
            authority=SourceAuthority.NATIONAL_AUTHORITY,
            snapshot_id=record.snapshot_id,
        )
        return DisasterEvent(
            event_id=f"cap:{record.sender}:{record.identifier}",
            hazard=query.hazard,
            location=record.area_description or query.country.canonical_name,
            country=query.country,
            event_time=record.sent,
            source=source,
            latitude=record.latitude,
            longitude=record.longitude,
            intensity=record.severity or None,
            provider_ids=(f"cap:{record.sender}:{record.identifier}",),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _xml(document: str) -> Element:
    try:
        return ElementTree.fromstring(document)
    except (ParseError, DefusedXmlException) as error:
        raise DisasterProviderResponseError(
            "The CAP XML document was malformed.", reason_code="malformed_xml"
        ) from error


def _parse_cap(root: Element, canonical_url: str) -> _CapRecord | None:
    if _local_name(root.tag) != "alert":
        raise DisasterProviderResponseError(
            "The document root was not a CAP alert.", reason_code="invalid_schema"
        )
    identifier = _child_text(root, "identifier")
    sender = _child_text(root, "sender")
    sent = normalize_timestamp(_child_text(root, "sent"))
    status = _child_text(root, "status")
    message_type = _child_text(root, "msgType")
    scope = _child_text(root, "scope")
    if not identifier or not sender or sent is None:
        raise DisasterProviderResponseError(
            "CAP alert identity was incomplete.", reason_code="invalid_schema"
        )
    if status != "Actual" or scope != "Public":
        return None
    if message_type not in {"Alert", "Update", "Cancel"}:
        return None
    info = next((item for item in root if _local_name(item.tag) == "info"), None)
    if info is None:
        raise DisasterProviderResponseError(
            "CAP alert contained no info block.", reason_code="invalid_schema"
        )
    area = next((item for item in info if _local_name(item.tag) == "area"), None)
    latitude, longitude = _polygon_centroid(
        _child_text(area, "polygon") if area is not None else ""
    )
    return _CapRecord(
        identifier=identifier,
        sender=sender,
        sent=sent.astimezone(UTC),
        message_type=message_type,
        event=_child_text(info, "event"),
        headline=_child_text(info, "headline"),
        description=_child_text(info, "description"),
        instruction=_child_text(info, "instruction"),
        severity=_child_text(info, "severity"),
        urgency=_child_text(info, "urgency"),
        certainty=_child_text(info, "certainty"),
        area_description=_child_text(area, "areaDesc") if area is not None else "",
        latitude=latitude,
        longitude=longitude,
        canonical_url=canonical_url,
    )


def _feed_links(root: Element) -> list[str]:
    links: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) != "link":
            continue
        value = (element.attrib.get("href") or element.text or "").strip()
        if value.startswith("https://"):
            links.append(value)
    return list(dict.fromkeys(links))


def _child_text(parent: Element | None, name: str) -> str:
    if parent is None:
        return ""
    for item in parent:
        if _local_name(item.tag) == name:
            return (item.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    return tag.rpartition("}")[2]


def _polygon_centroid(value: str) -> tuple[float | None, float | None]:
    points: list[tuple[float, float]] = []
    for pair in value.split():
        latitude, separator, longitude = pair.partition(",")
        if not separator:
            continue
        try:
            points.append((float(latitude), float(longitude)))
        except ValueError:
            return None, None
    if not points:
        return None, None
    return (
        sum(item[0] for item in points) / len(points),
        sum(item[1] for item in points) / len(points),
    )


def _matches_hazard(event: str, hazard: Hazard) -> bool:
    normalized = event.casefold()
    terms = {
        Hazard.EARTHQUAKE: ("earthquake", "quake", "seismic"),
        Hazard.TSUNAMI: ("tsunami",),
        Hazard.FLOOD: ("flood", "inundation"),
        Hazard.WILDFIRE: ("wildfire", "forest fire"),
        Hazard.LANDSLIDE: ("landslide", "mudslide"),
        Hazard.TROPICAL_CYCLONE: ("cyclone", "typhoon", "hurricane"),
    }[hazard]
    return any(term in normalized for term in terms)
