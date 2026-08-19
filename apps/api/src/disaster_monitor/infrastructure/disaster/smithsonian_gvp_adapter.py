"""Bounded Smithsonian/USGS volcanic-eruption event discovery."""

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from typing import cast
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from disaster_monitor.application.disaster import (
    DisasterQuery,
    ProviderBatch,
    ProviderIssue,
    WorldwideDisasterEvent,
    WorldwideDisasterQuery,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.domain.disaster import (
    Country,
    Disaster,
    DisasterEvent,
    EventGeographyStatus,
    SourceAuthority,
    SourceReference,
    point_event_geometry,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    HttpParam,
    SourcePayloadRecorder,
    build_snapshot_capture,
    get_json,
    get_text,
)

WVAR_URL = "https://volcano.si.edu/reports_weekly.cfm"
GVP_WFS_URL = "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows"
_MAX_SEARCH_DAYS = 30
_MAX_FEATURES = 100
_ADMITTED_REPORT_TYPES = frozenset(
    {"New Eruptive Activity", "Continuing Eruptive Activity"}
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ),
        start=1,
    )
}
_SOURCE_DATE = re.compile(
    r"(?P<year>20\d{2})\s+(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})"
)
_VOLCANO_PROFILE = re.compile(r"volcano\.cfm\?[^\"']*\bvn=(\d{6})", re.I)
_REPORT_LINK = re.compile(r"(?:[?&](?:wvar|gvpvar)=)([^&#\"']+)", re.I)
_REPORT_IDENTIFIER = re.compile(r"-([0-9]{6})$")


@dataclass(frozen=True, slots=True)
class _SummaryCell:
    text: str
    links: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _WvarRow:
    name: str
    country: str
    region: str
    start_text: str
    report_type: str
    volcano_number: int | None
    report_id: str | None
    report_url: str | None


@dataclass(frozen=True, slots=True)
class _GvpVolcano:
    number: int
    name: str
    countries: tuple[str, ...]
    region: str
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class _GvpEruption:
    volcano_number: int
    eruption_number: int
    start: date


class _WvarSummaryParser(HTMLParser):
    """Extract the one WVAR summary table and source-owned report links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._table_depth = 0
        self._row: list[_SummaryCell] | None = None
        self._cell_text: list[str] | None = None
        self._cell_links: list[str] = []
        self._tables: list[tuple[tuple[_SummaryCell, ...], ...]] = []
        self._table_rows: list[tuple[_SummaryCell, ...]] = []
        self.report_ids: dict[int, str] = {}
        self.report_urls: dict[int, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = dict(attrs)
        href = attributes.get("href")
        if tag == "a" and href:
            match = _REPORT_LINK.search(href)
            if match:
                identifier = unquote(match.group(1)).strip()
                volcano_match = _REPORT_IDENTIFIER.search(identifier)
                if volcano_match:
                    volcano_number = int(volcano_match.group(1))
                    self.report_ids[volcano_number] = identifier
                    self.report_urls[volcano_number] = href
            if self._cell_text is not None:
                self._cell_links.append(href)
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table_rows = []
        elif self._table_depth == 1 and tag == "tr":
            self._row = []
        elif self._table_depth == 1 and tag in {"td", "th"}:
            self._cell_text = []
            self._cell_links = []

    def handle_data(self, data: str) -> None:
        if self._cell_text is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._table_depth == 1 and tag in {"td", "th"}:
            if self._row is not None and self._cell_text is not None:
                self._row.append(
                    _SummaryCell(
                        " ".join("".join(self._cell_text).split()),
                        tuple(self._cell_links),
                    )
                )
            self._cell_text = None
            self._cell_links = []
        elif self._table_depth == 1 and tag == "tr":
            if self._row:
                self._table_rows.append(tuple(self._row))
            self._row = None
        elif tag == "table" and self._table_depth:
            if self._table_depth == 1 and self._table_rows:
                self._tables.append(tuple(self._table_rows))
            self._table_depth -= 1

    def rows(self) -> tuple[_WvarRow, ...]:
        required = {
            "name",
            "country",
            "volcanic region",
            "eruption start date",
            "report type",
        }
        for table in self._tables:
            if not table:
                continue
            headers = {
                cell.text.casefold(): index for index, cell in enumerate(table[0])
            }
            if not required.issubset(headers):
                continue
            rows: list[_WvarRow] = []
            for cells in table[1:]:
                values = {
                    key: cells[index].text if index < len(cells) else ""
                    for key, index in headers.items()
                }
                profile_links = (
                    cells[headers["name"]].links if headers["name"] < len(cells) else ()
                )
                number = next(
                    (
                        int(match.group(1))
                        for link in profile_links
                        if (match := _VOLCANO_PROFILE.search(link))
                    ),
                    None,
                )
                rows.append(
                    _WvarRow(
                        values.get("name", ""),
                        values.get("country", ""),
                        values.get("volcanic region", ""),
                        values.get("eruption start date", ""),
                        values.get("report type", ""),
                        number,
                        self.report_ids.get(number) if number is not None else None,
                        self.report_urls.get(number) if number is not None else None,
                    )
                )
            return tuple(rows)
        return ()


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _precise_wvar_date(value: str) -> date | None:
    text = " ".join(value.split())
    if not text or any(
        marker in text.casefold() for marker in ("—", "-", "?", "±", "in or before")
    ):
        return None
    match = _SOURCE_DATE.fullmatch(text)
    if not match:
        return None
    try:
        return date(
            int(match.group("year")),
            _MONTHS[match.group("month").title()],
            int(match.group("day")),
        )
    except (KeyError, ValueError):
        return None


def _precise_wfs_date(properties: dict[str, object]) -> date | None:
    for key in ("StartDateYearModifier", "StartDateDayModifier"):
        value = properties.get(key)
        if value is not None and value != "":
            return None
    for key in ("StartDateYearUncertainty", "StartDateDayUncertainty"):
        value = properties.get(key)
        if value is not None and value not in {0, "", "0"}:
            return None
    year = properties.get("StartDateYear")
    month = properties.get("StartDateMonth")
    day = properties.get("StartDateDay")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (year, month, day)
    ):
        return None
    try:
        return date(cast(int, year), cast(int, month), cast(int, day))
    except (TypeError, ValueError):
        return None


def _wfs_filter(numbers: tuple[int, ...]) -> str:
    return "Volcano_Number IN (" + ",".join(str(number) for number in numbers) + ")"


def _wfs_params(
    type_name: str, fields: tuple[str, ...], numbers: tuple[int, ...]
) -> dict[str, HttpParam]:
    return {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_name,
        "outputFormat": "application/json",
        "count": _MAX_FEATURES,
        "propertyName": ",".join(fields),
        "CQL_FILTER": _wfs_filter(numbers),
    }


def _feature_collection(payload: object, label: str) -> list[object]:
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise DisasterProviderResponseError(
            f"The GVP {label} response was not a GeoJSON FeatureCollection.",
            reason_code="malformed_json",
        )
    features = payload.get("features")
    if not isinstance(features, list):
        raise DisasterProviderResponseError(
            f"The GVP {label} response had no feature list.",
            reason_code="malformed_json",
        )
    return features


def _source_report_url(href: str | None) -> str | None:
    if not href:
        return None
    url = urljoin(f"{WVAR_URL}/", href)
    target = urlsplit(url)
    if (
        target.scheme.lower() != "https"
        or target.hostname not in {"volcano.si.edu"}
        or target.username is not None
        or target.password is not None
        or target.port not in {None, 443}
    ):
        return None
    return url


def _parse_volcano_feature(
    raw: object, index: int
) -> tuple[_GvpVolcano | None, ProviderIssue | None]:
    try:
        if not isinstance(raw, dict) or not isinstance(raw.get("properties"), dict):
            raise ValueError("properties are missing")
        properties = raw["properties"]
        number = properties.get("Volcano_Number")
        name = _text(properties.get("Volcano_Name"))
        country = _text(properties.get("Country"))
        region = _text(properties.get("Region"))
        latitude = properties.get("Latitude")
        longitude = properties.get("Longitude")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ValueError("Volcano_Number is invalid")
        if not name or not country:
            raise ValueError("volcano name or country is missing")
        if not isinstance(latitude, (int, float)) or isinstance(latitude, bool):
            raise ValueError("Latitude is invalid")
        if not isinstance(longitude, (int, float)) or isinstance(longitude, bool):
            raise ValueError("Longitude is invalid")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("coordinates are outside the WGS84 extent")
    except (TypeError, ValueError, OverflowError) as error:
        return None, ProviderIssue(
            "Smithsonian / USGS Weekly Volcanic Activity Report",
            "A malformed GVP volcano record was skipped.",
            reason_code="invalid_record",
            detail=f"volcanoes.features[{index}]: {error}",
        )
    return _GvpVolcano(
        number, name, (country,), region, float(latitude), float(longitude)
    ), None


def _parse_eruption_feature(
    raw: object, index: int
) -> tuple[_GvpEruption | None, ProviderIssue | None]:
    try:
        if not isinstance(raw, dict) or not isinstance(raw.get("properties"), dict):
            raise ValueError("properties are missing")
        properties = raw["properties"]
        volcano_number = properties.get("Volcano_Number")
        eruption_number = properties.get("Eruption_Number")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (volcano_number, eruption_number)
        ):
            raise ValueError("eruption identifiers are invalid")
        start = _precise_wfs_date(properties)
        if start is None:
            return None, None
    except (TypeError, ValueError, OverflowError) as error:
        return None, ProviderIssue(
            "Smithsonian / USGS Weekly Volcanic Activity Report",
            "A malformed GVP eruption record was skipped.",
            reason_code="invalid_record",
            detail=f"eruptions.features[{index}]: {error}",
        )
    return _GvpEruption(volcano_number, eruption_number, start), None


def _week_starts(start: datetime, end: datetime) -> tuple[date, ...]:
    starts: list[date] = []
    cursor = start.date() - timedelta(days=7)
    while cursor <= end.date():
        weekday = 3 if cursor.year >= 2026 else 2
        candidate = cursor - timedelta(days=(cursor.weekday() - weekday) % 7)
        if (
            candidate not in starts
            and candidate <= end.date()
            and candidate + timedelta(days=6) >= start.date()
        ):
            starts.append(candidate)
        cursor += timedelta(days=1)
    return tuple(sorted(starts))


class SmithsonianGvpAdapter:
    """Discover explicit WVAR eruptive-activity candidates with GVP metadata."""

    provider_name = "Smithsonian / USGS Weekly Volcanic Activity Report"
    source_id = "smithsonian-usgs-volcanic-activity"
    allowed_hosts = frozenset({"volcano.si.edu", "webservices.volcano.si.edu"})

    def __init__(
        self,
        *,
        geography: CountryCatalog,
        client: httpx.AsyncClient | None = None,
        snapshot_recorder: SourcePayloadRecorder | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._geography = geography
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._snapshot_recorder = snapshot_recorder
        self._max_response_bytes = max_response_bytes

    def _interval(
        self, query: DisasterQuery | WorldwideDisasterQuery, now: datetime
    ) -> tuple[datetime, datetime]:
        requested_days = min(
            _MAX_SEARCH_DAYS,
            max(0, query.time_window_days),
        )
        start = getattr(query, "date_from", None) or now - timedelta(
            days=requested_days
        )
        end = getattr(query, "date_to", None) or now
        if end - start > timedelta(days=_MAX_SEARCH_DAYS):
            start = end - timedelta(days=_MAX_SEARCH_DAYS)
        return start, end

    async def _wvar_page(
        self, week_start: date, now: datetime
    ) -> tuple[tuple[_WvarRow, ...], str | None]:
        weekstart = week_start.strftime("%Y%m%d")
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={"weekstart": weekstart},
            rights_id="smithsonian-gvp-wvar-terms-2026-08",
            retrieved_at=now,
        )
        html = await get_text(
            self._client,
            WVAR_URL,
            params={"weekstart": weekstart},
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        parser = _WvarSummaryParser()
        parser.feed(html)
        parser.close()
        rows = parser.rows()
        if not rows:
            raise DisasterProviderResponseError(
                "The WVAR response did not contain its summary table.",
                reason_code="malformed_response",
            )
        return (
            rows,
            capture.snapshot.snapshot_id if capture and capture.snapshot else None,
        )

    async def _gvp_volcanoes(
        self, numbers: tuple[int, ...], now: datetime
    ) -> tuple[dict[int, _GvpVolcano], list[ProviderIssue]]:
        if not numbers:
            return {}, []
        params = _wfs_params(
            "GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes",
            (
                "Volcano_Number",
                "Volcano_Name",
                "Country",
                "Region",
                "Latitude",
                "Longitude",
            ),
            numbers,
        )
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "layer": "volcanoes",
                "volcano_numbers": ",".join(map(str, numbers)),
            },
            rights_id="smithsonian-gvp-votw-terms-2026-08",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            GVP_WFS_URL,
            params=params,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        parsed: dict[int, _GvpVolcano] = {}
        issues: list[ProviderIssue] = []
        for index, raw in enumerate(_feature_collection(payload, "volcano")):
            feature, issue = _parse_volcano_feature(raw, index)
            if feature is not None and feature.number not in parsed:
                parsed[feature.number] = feature
            if issue is not None:
                issues.append(issue)
        return parsed, issues

    async def _gvp_eruptions(
        self, numbers: tuple[int, ...], now: datetime
    ) -> tuple[tuple[_GvpEruption, ...], list[ProviderIssue]]:
        if not numbers:
            return (), []
        params = _wfs_params(
            "GVP-VOTW:Smithsonian_VOTW_Holocene_Eruptions",
            (
                "Volcano_Number",
                "Eruption_Number",
                "StartDateYearModifier",
                "StartDateYear",
                "StartDateYearUncertainty",
                "StartDateDayModifier",
                "StartDateMonth",
                "StartDateDay",
                "StartDateDayUncertainty",
            ),
            numbers,
        )
        capture = build_snapshot_capture(
            self._snapshot_recorder,
            source_id=self.source_id,
            parameters={
                "layer": "eruptions",
                "volcano_numbers": ",".join(map(str, numbers)),
            },
            rights_id="smithsonian-gvp-votw-terms-2026-08",
            retrieved_at=now,
        )
        payload = await get_json(
            self._client,
            GVP_WFS_URL,
            params=params,
            allowed_hosts=self.allowed_hosts,
            max_bytes=self._max_response_bytes,
            provider_name=self.provider_name,
            capture=capture,
        )
        records: list[_GvpEruption] = []
        issues: list[ProviderIssue] = []
        for index, raw in enumerate(_feature_collection(payload, "eruption")):
            record, issue = _parse_eruption_feature(raw, index)
            if record is not None:
                records.append(record)
            if issue is not None:
                issues.append(issue)
        return tuple(records), issues

    def _resolve_time(
        self,
        row: _WvarRow,
        week_start: date,
        eruptions: tuple[_GvpEruption, ...],
    ) -> tuple[date, str | None] | None:
        wvar_start = _precise_wvar_date(row.start_text)
        candidates = tuple(
            item for item in eruptions if item.volcano_number == row.volcano_number
        )
        if wvar_start is not None:
            matched = next(
                (item for item in candidates if item.start == wvar_start), None
            )
            return (
                wvar_start,
                f"gvp-eruption:{matched.eruption_number}" if matched else None,
            )
        in_week = tuple(
            item
            for item in candidates
            if week_start - timedelta(days=30)
            <= item.start
            <= week_start + timedelta(days=6)
        )
        if len(in_week) == 1:
            return in_week[0].start, f"gvp-eruption:{in_week[0].eruption_number}"
        return None

    def _source(
        self,
        row: _WvarRow,
        week_start: date,
        now: datetime,
        snapshot_id: str | None,
    ) -> SourceReference:
        weekstart = week_start.strftime("%Y%m%d")
        return SourceReference(
            source_id=self.source_id,
            publisher=(
                "Smithsonian Global Volcanism Program / USGS Volcano Hazards Program"
            ),
            title="Smithsonian / USGS Weekly Volcanic Activity Report",
            canonical_url=(
                _source_report_url(row.report_url)
                or f"{WVAR_URL}?weekstart={weekstart}"
            ),
            published_at=None,
            updated_at=None,
            retrieved_at=now,
            authority=SourceAuthority.SCIENTIFIC_AUTHORITY,
            snapshot_id=snapshot_id,
        )

    def _affiliated_codes(self, volcano: _GvpVolcano) -> frozenset[str]:
        return frozenset(
            country.alpha3_code
            for label in volcano.countries
            for country in self._geography.find_mentions(label)
        )

    def _candidate(
        self,
        row: _WvarRow,
        volcano: _GvpVolcano,
        eruption: tuple[date, str | None],
        *,
        week_start: date,
        snapshot_id: str | None,
        country: Country | None,
        now: datetime,
    ) -> DisasterEvent | WorldwideDisasterEvent | None:
        event_date, eruption_id = eruption
        source = self._source(row, week_start, now, snapshot_id)
        provider_ids = [f"gvp-volcano:{volcano.number}"]
        if eruption_id is not None:
            provider_ids.append(eruption_id)
        if row.report_id:
            provider_ids.append(f"wvar:{row.report_id}")
        location = volcano.name + (f", {volcano.region}" if volcano.region else "")
        geometry = point_event_geometry(volcano.latitude, volcano.longitude, source)
        if country is None:
            return WorldwideDisasterEvent(
                event_id=eruption_id
                or f"gvp-eruption:{volcano.number}:{event_date:%Y%m%d}",
                disaster=Disaster.VOLCANIC_ERUPTION,
                location=location,
                event_time=datetime(
                    event_date.year, event_date.month, event_date.day, tzinfo=UTC
                ),
                source=source,
                geometry=geometry,
                provider_ids=tuple(provider_ids),
            )
        geography_status = EventGeographyStatus.IN_COUNTRY
        if not self._geography.contains(country, volcano.latitude, volcano.longitude):
            if country.alpha3_code not in self._affiliated_codes(volcano):
                return None
            geography_status = EventGeographyStatus.COUNTRY_ASSOCIATED_OFFSHORE
        return DisasterEvent(
            event_id=eruption_id
            or f"gvp-eruption:{volcano.number}:{event_date:%Y%m%d}",
            disaster=Disaster.VOLCANIC_ERUPTION,
            location=location,
            country=country,
            event_time=datetime(
                event_date.year, event_date.month, event_date.day, tzinfo=UTC
            ),
            source=source,
            geometry=geometry,
            provider_ids=tuple(provider_ids),
            geography_status=geography_status,
        )

    async def _discover(
        self,
        query: DisasterQuery | WorldwideDisasterQuery,
        *,
        now: datetime,
        country: Country | None,
    ) -> ProviderBatch[DisasterEvent | WorldwideDisasterEvent]:
        start, end = self._interval(query, now)
        if end < start:
            return ProviderBatch(
                issues=(
                    ProviderIssue(
                        self.provider_name,
                        "The volcanic-eruption time interval is invalid.",
                        reason_code="invalid_query",
                    ),
                )
            )
        rows: list[tuple[_WvarRow, date, str | None, str | None]] = []
        issues: list[ProviderIssue] = []
        for week_start in _week_starts(start, end):
            page_rows, snapshot_id = await self._wvar_page(week_start, now)
            for row in page_rows:
                report_type = " ".join(row.report_type.split())
                if report_type not in _ADMITTED_REPORT_TYPES:
                    issues.append(
                        ProviderIssue(
                            self.provider_name,
                            (
                                f"WVAR report type {report_type or '<missing>'!r} was "
                                "not admitted as an eruption."
                            ),
                            reason_code=(
                                "unsupported_report_type"
                                if report_type
                                not in {
                                    "New Unrest",
                                    "Continuing Unrest",
                                    "Other Observations",
                                }
                                else "non_eruptive_report_type"
                            ),
                        )
                    )
                    continue
                if row.volcano_number is None or not row.name or not row.country:
                    issues.append(
                        ProviderIssue(
                            self.provider_name,
                            "A malformed WVAR candidate was skipped.",
                            reason_code="invalid_record",
                        )
                    )
                    continue
                rows.append((row, week_start, snapshot_id, None))
        if not rows:
            if not issues:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "WVAR returned no admitted eruptive activity.",
                        reason_code="empty_result",
                    )
                )
            return ProviderBatch(issues=tuple(issues))
        numbers = tuple(
            sorted(
                {
                    row.volcano_number
                    for row, _, _, _ in rows
                    if row.volcano_number is not None
                }
            )
        )[:_MAX_FEATURES]
        volcanoes, volcano_issues = await self._gvp_volcanoes(numbers, now)
        issues.extend(volcano_issues)
        needs_eruptions = bool(rows)
        eruptions, eruption_issues = (
            await self._gvp_eruptions(numbers, now) if needs_eruptions else ((), [])
        )
        issues.extend(eruption_issues)
        records: dict[str, DisasterEvent | WorldwideDisasterEvent] = {}
        for row, week_start, snapshot_id, _ in rows:
            if row.volcano_number is None:
                continue
            volcano = volcanoes.get(row.volcano_number)
            if volcano is None:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "A WVAR volcano had no matched GVP identity or geography.",
                        reason_code="gvp_identity_unavailable",
                    )
                )
                continue
            resolved = self._resolve_time(row, week_start, eruptions)
            if resolved is None:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "A volcanic candidate had no day-precise eruption start.",
                        reason_code="event_time_precision_unavailable",
                    )
                )
                continue
            record = self._candidate(
                row,
                volcano,
                resolved,
                week_start=week_start,
                snapshot_id=snapshot_id,
                country=country,
                now=now,
            )
            if record is None:
                issues.append(
                    ProviderIssue(
                        self.provider_name,
                        "A GVP point and affiliation failed country validation.",
                        reason_code="country_mismatch",
                    )
                )
                continue
            existing = records.get(record.event_id)
            if existing is None:
                records[record.event_id] = record
            else:
                records[record.event_id] = _merge_provider_ids(existing, record)
        if not records and not issues:
            issues.append(
                ProviderIssue(
                    self.provider_name,
                    "No valid volcanic-eruption records were found.",
                    reason_code="empty_result",
                )
            )
        return ProviderBatch[DisasterEvent | WorldwideDisasterEvent](
            records=tuple(records.values()), issues=tuple(issues)
        )

    async def find_recent_events(
        self, query: DisasterQuery, *, now: datetime
    ) -> ProviderBatch[DisasterEvent]:
        if query.disaster is not Disaster.VOLCANIC_ERUPTION:
            return ProviderBatch()
        batch = await self._discover(query, now=now, country=query.country)
        return ProviderBatch[DisasterEvent](
            records=tuple(
                record for record in batch.records if isinstance(record, DisasterEvent)
            ),
            issues=batch.issues,
        )

    async def find_worldwide_events(
        self, query: WorldwideDisasterQuery, *, now: datetime
    ) -> ProviderBatch[WorldwideDisasterEvent]:
        if query.disaster is not Disaster.VOLCANIC_ERUPTION or query.limit <= 0:
            return ProviderBatch()
        batch = await self._discover(query, now=now, country=None)
        records = tuple(
            record
            for record in batch.records
            if isinstance(record, WorldwideDisasterEvent)
        )
        return ProviderBatch[WorldwideDisasterEvent](
            records=tuple(
                record for record in records[: min(query.limit, _MAX_FEATURES)]
            ),
            issues=batch.issues,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _merge_provider_ids(
    first: DisasterEvent | WorldwideDisasterEvent,
    second: DisasterEvent | WorldwideDisasterEvent,
) -> DisasterEvent | WorldwideDisasterEvent:
    ids = tuple(dict.fromkeys((*first.provider_ids, *second.provider_ids)))
    return replace(first, provider_ids=ids)
