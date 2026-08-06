"""Adapters for Japan Meteorological Agency JSON earthquake and tsunami feeds."""

import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
)
from disaster_monitor.application.services.evidence_reconciliation import (
    normalize_timestamp,
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
    DisasterProviderError,
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import get_json, get_text

JMA_EARTHQUAKE_LIST_URL = "https://www.jma.go.jp/bosai/quake/data/list.json"
JMA_TSUNAMI_LIST_URL = "https://www.jma.go.jp/bosai/tsunami/data/list.json"
JMA_DATA_BASE_URL = "https://www.jma.go.jp/bosai/quake/data/"
JMA_TSUNAMI_DATA_BASE_URL = "https://www.jma.go.jp/bosai/tsunami/data/"
JMA_EEW_HISTORY_URL = "https://www.data.jma.go.jp/eew/data/nc/pub_hist/index.html"
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
            provider_name=self.provider_name,
        )
        if not isinstance(payload, list):
            raise DisasterProviderResponseError(
                "The JMA earthquake response was not a list."
            )
        events: list[DisasterEvent] = []
        start = query.date_from or now - timedelta(days=query.time_window_days)
        end = query.date_to or now + timedelta(minutes=5)
        for item in payload[:200]:
            if not isinstance(item, dict):
                continue
            event_time = normalize_timestamp(item.get("at"))
            latitude, longitude, depth_km = _parse_jma_code(item.get("cod"))
            event_id = _safe_string(item.get("eid"))
            if not event_id or event_time is None or not _is_japan(latitude, longitude):
                continue
            if not start <= event_time <= end:
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
                authority=SourceAuthority.NATIONAL_AUTHORITY,
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
                    hazard=Hazard.EARTHQUAKE,
                    location=location or "Japan",
                    country=query.country,
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
                    provider_ids=(f"jma:{event_id}",),
                )
            )
        if not events:
            return ProviderBatch(
                issues=(
                    ProviderIssue(
                        self.provider_name,
                        f"{self.provider_name}: The provider returned no matching "
                        "records.",
                        reason_code="empty_result",
                    ),
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
            provider_name=self.provider_name,
        )
        if not isinstance(payload, list):
            raise DisasterProviderResponseError(
                "The JMA tsunami response was not a list."
            )
        raw_event_id = event.jma_event_id
        if raw_event_id is None:
            return ProviderBatch(records=())
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
                authority=SourceAuthority.NATIONAL_AUTHORITY,
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
                    countries=(query.country.canonical_name,),
                    country_codes=(query.country.alpha3_code,),
                    hazard=query.hazard,
                )
            )
        if not reports:
            return ProviderBatch(records=())
        return ProviderBatch(records=tuple(reports))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class _JmaHistoryParser(HTMLParser):
    """Parse table rows without depending on the current page's visual layout."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[list[str], str, dict[str, str]]] = []
        self._cells: list[str] | None = None
        self._cell_parts: list[str] = []
        self._href = ""
        self._attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._cells = []
            self._href = ""
            self._attrs = dict((key, value or "") for key, value in attrs)
        elif self._cells is not None and tag in {"td", "th"}:
            self._cell_parts = []
        elif self._cells is not None and tag == "a":
            values = dict((key, value or "") for key, value in attrs)
            self._href = values.get("href", self._href)

    def handle_data(self, data: str) -> None:
        if self._cells is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._cells is None:
            return
        if tag in {"td", "th"}:
            self._cells.append(" ".join(self._cell_parts).strip())
            self._cell_parts = []
        elif tag == "tr":
            if self._cells:
                self.rows.append((self._cells, self._href, self._attrs))
            self._cells = None


def _history_timestamp(value: str) -> datetime | None:
    value = value.strip()
    for pattern in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, pattern).replace(
                tzinfo=timezone(timedelta(hours=9))
            )
        except ValueError:
            continue
    return normalize_timestamp(value)


def _history_number(value: str) -> float | None:
    match = re.search(r"(?:M\s*)?(\d+(?:\.\d+)?)", value, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _history_intensity(value: str) -> str | None:
    value = value.strip()
    if not value or value in {"---", "-"}:
        return None
    return f"JMA {value}"


def _history_event_id(href: str, event_time: datetime) -> str:
    match = re.search(r"(\d{14})", href)
    return match.group(1) if match else event_time.strftime("%Y%m%d%H%M%S")


def _detail_coordinates(text: str) -> tuple[float | None, float | None, float | None]:
    latitude = _degree_coordinate(text, r"(?:北緯|latitude)")
    longitude = _degree_coordinate(text, r"(?:東経|longitude)")
    depth = re.search(r"(?:深さ|depth)\D{0,30}(\d+(?:\.\d+)?)", text, re.I)
    return (
        latitude,
        longitude,
        float(depth.group(1)) if depth else None,
    )


def _degree_coordinate(text: str, label: str) -> float | None:
    """Parse decimal degrees or Japanese degree/minute coordinates."""
    match = re.search(
        rf"{label}\s*(\d+(?:\.\d+)?)\s*(?:度|degrees?)"
        rf"(?:\s*(\d+(?:\.\d+)?)\s*(?:分|minutes?))?",
        text,
        re.I,
    )
    if not match:
        return None
    degrees = float(match.group(1))
    minutes = float(match.group(2)) if match.group(2) else 0.0
    return degrees + minutes / 60


class JmaSignificantEarthquakeAdapter:
    """Discover warning-level JMA earthquakes retained beyond the rolling list."""

    provider_name = "JMA significant"

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
        markup = await get_text(
            self._client,
            JMA_EEW_HISTORY_URL,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
        )
        parser = _JmaHistoryParser()
        try:
            parser.feed(markup)
        except Exception as error:
            raise DisasterProviderResponseError(
                "The JMA significant-event history could not be parsed.",
                reason_code="invalid_payload",
            ) from error
        start = query.date_from or now - timedelta(days=query.time_window_days)
        end = query.date_to or now + timedelta(minutes=5)
        events: list[DisasterEvent] = []
        for cells, href, attrs in parser.rows:
            if len(cells) < 4:
                continue
            event_time = _history_timestamp(cells[0])
            magnitude = _history_number(cells[2])
            if (
                event_time is None
                or magnitude is None
                or not start <= event_time <= end
            ):
                continue
            event_id = _history_event_id(href, event_time)
            latitude = _number_from_attr(attrs, "latitude")
            longitude = _number_from_attr(attrs, "longitude")
            depth_km = _number_from_attr(attrs, "depth")
            detail_url = urljoin(JMA_EEW_HISTORY_URL, href) if href else None
            if detail_url and (latitude is None or longitude is None):
                try:
                    detail = await get_text(
                        self._client,
                        detail_url,
                        max_bytes=self._max_response_bytes,
                        provider_name=self.provider_name,
                    )
                    latitude, longitude, detail_depth = _detail_coordinates(detail)
                    depth_km = depth_km or detail_depth
                except DisasterProviderError:
                    # The index is still a valid significant-event record.
                    pass
            source = SourceReference(
                publisher="Japan Meteorological Agency",
                title=f"Emergency earthquake warning history — {cells[1]}",
                canonical_url=detail_url or JMA_EEW_HISTORY_URL,
                published_at=event_time,
                updated_at=event_time,
                retrieved_at=now,
                authority=SourceAuthority.NATIONAL_AUTHORITY,
            )
            events.append(
                DisasterEvent(
                    event_id=f"jma:{event_id}",
                    hazard=Hazard.EARTHQUAKE,
                    location=cells[1] or "Japan",
                    country=query.country,
                    event_time=event_time,
                    source=source,
                    latitude=latitude,
                    longitude=longitude,
                    magnitude=magnitude,
                    magnitude_type="Mj",
                    intensity=_history_intensity(cells[3]),
                    depth_km=depth_km,
                    significance=magnitude * 100 + _intensity_score(cells[3]) * 100,
                    provider_ids=(f"jma:{event_id}",),
                )
            )
        if not events:
            return ProviderBatch(
                issues=(
                    ProviderIssue(
                        self.provider_name,
                        f"{self.provider_name}: The provider returned no matching "
                        "records.",
                        reason_code="empty_result",
                    ),
                )
            )
        return ProviderBatch(records=tuple(events))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _number_from_attr(attrs: dict[str, str], name: str) -> float | None:
    value = attrs.get(name, attrs.get(f"data-{name}", ""))
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _intensity_score(value: str) -> int:
    return {
        "7": 7,
        "６強": 6,
        "６弱": 5,
        "６": 5,
        "５強": 4,
        "５弱": 3,
        "５": 3,
        "４": 2,
        "３": 1,
    }.get(value.strip(), 0)
