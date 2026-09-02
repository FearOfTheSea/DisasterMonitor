"""Bounded Smithsonian/USGS volcanic-eruption event discovery."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import cast
from urllib.parse import unquote, urljoin, urlsplit
from xml.etree import ElementTree

from disaster_monitor.application.disaster import (
    ProviderIssue,
)
from disaster_monitor.infrastructure.disaster.errors import (
    DisasterProviderResponseError,
)
from disaster_monitor.infrastructure.disaster.http import (
    HttpParam,
)

WVAR_URL = "https://volcano.si.edu/reports_weekly.cfm"
WVAR_RSS_URL = "https://volcano.si.edu/news/WeeklyVolcanoRSS.xml"
GVP_WFS_URL = "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows"
_MAX_SEARCH_DAYS = 30
_MAX_FEATURES = 100
_MAX_ERUPTION_FEATURES = 2_000
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
_FULL_MONTHS = {
    name.casefold(): number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
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
_RSS_TITLE = re.compile(
    r"^(?P<name>.+?) \((?P<country>[^()]+)\) - Report for "
    r"(?P<start_day>\d{1,2}) (?P<start_month>[A-Za-z]+)-"
    r"(?P<end_day>\d{1,2}) (?P<end_month>[A-Za-z]+) "
    r"(?P<end_year>20\d{2}) - (?P<report_type>.+)$"
)
_RSS_VOLCANO = re.compile(r"vn_(\d{6})$")


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
class _WvarFeedEntry:
    row: _WvarRow
    week_start: date
    published_at: datetime


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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = dict(attrs)
        href = attributes.get("href")
        if tag == "a" and href:
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
                row_report = next(
                    (
                        (identifier, href)
                        for cell in cells
                        for href in cell.links
                        if (match := _REPORT_LINK.search(href))
                        and (identifier := unquote(match.group(1)).strip())
                        and (volcano_match := _REPORT_IDENTIFIER.search(identifier))
                        and number is not None
                        and int(volcano_match.group(1)) == number
                    ),
                    (None, None),
                )
                rows.append(
                    _WvarRow(
                        values.get("name", ""),
                        values.get("country", ""),
                        values.get("volcanic region", ""),
                        values.get("eruption start date", ""),
                        values.get("report type", ""),
                        number,
                        row_report[0],
                        row_report[1],
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


def _parse_rss_title(value: str) -> tuple[str, str, date, str] | None:
    match = _RSS_TITLE.fullmatch(" ".join(value.split()))
    if match is None:
        return None
    try:
        start_month = _FULL_MONTHS[match.group("start_month").casefold()]
        end_month = _FULL_MONTHS[match.group("end_month").casefold()]
        end_year = int(match.group("end_year"))
        start_year = end_year - 1 if start_month > end_month else end_year
        week_start = date(start_year, start_month, int(match.group("start_day")))
        week_end = date(end_year, end_month, int(match.group("end_day")))
    except (KeyError, ValueError):
        return None
    if week_end - week_start != timedelta(days=6):
        return None
    return (
        match.group("name").strip(),
        match.group("country").strip(),
        week_start,
        match.group("report_type").strip(),
    )


def _parse_wvar_rss(
    xml: str, provider_name: str
) -> tuple[tuple[_WvarFeedEntry, ...], tuple[ProviderIssue, ...]]:
    if "<!doctype" in xml.casefold() or "<!entity" in xml.casefold():
        raise DisasterProviderResponseError(
            "The WVAR RSS response contained a prohibited XML declaration.",
            reason_code="malformed_response",
        )
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise DisasterProviderResponseError(
            "The WVAR RSS response was not well-formed XML.",
            reason_code="malformed_response",
        ) from error
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise DisasterProviderResponseError(
            "The WVAR RSS response had no channel.",
            reason_code="malformed_response",
        )
    items = channel.findall("item")
    if not items:
        raise DisasterProviderResponseError(
            "The WVAR RSS response contained no report items.",
            reason_code="malformed_response",
        )
    entries: list[_WvarFeedEntry] = []
    issues: list[ProviderIssue] = []
    for index, item in enumerate(items):
        title = _text(item.findtext("title"))
        guid = _text(item.findtext("guid"))
        published_text = _text(item.findtext("pubDate"))
        parsed_title = _parse_rss_title(title)
        report_url = _source_report_url(guid)
        try:
            published_at = parsedate_to_datetime(published_text)
        except (TypeError, ValueError):
            published_at = None
        if published_at is not None and published_at.tzinfo is not None:
            published_at = published_at.astimezone(UTC)
        else:
            published_at = None
        volcano_match = (
            _RSS_VOLCANO.fullmatch(urlsplit(report_url).fragment)
            if report_url
            else None
        )
        if parsed_title is None or volcano_match is None or published_at is None:
            issues.append(
                ProviderIssue(
                    provider_name,
                    "A malformed WVAR RSS item was skipped.",
                    reason_code="invalid_record",
                    detail=f"channel.item[{index}]",
                )
            )
            continue
        name, country, week_start, report_type = parsed_title
        volcano_number = int(volcano_match.group(1))
        entries.append(
            _WvarFeedEntry(
                _WvarRow(
                    name=name,
                    country=country,
                    region="",
                    start_text="",
                    report_type=report_type,
                    volcano_number=volcano_number,
                    report_id=f"rss:{week_start:%Y%m%d}:{volcano_number}",
                    report_url=report_url,
                ),
                week_start,
                published_at,
            )
        )
    return tuple(entries), tuple(issues)


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
    type_name: str,
    fields: tuple[str, ...],
    numbers: tuple[int, ...],
    *,
    count: int = _MAX_FEATURES,
) -> dict[str, HttpParam]:
    return {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_name,
        "outputFormat": "application/json",
        "count": count,
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
        or (target.hostname or "").lower().rstrip(".") not in {"volcano.si.edu"}
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
