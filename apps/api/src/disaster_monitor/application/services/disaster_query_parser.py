"""Deterministic disaster intent parsing backed by a country catalog."""

import re
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from disaster_monitor.application.disaster import (
    DisasterQuery,
    DisasterQueryParseResult,
    QueryParseStatus,
    RequestClassification,
    RequestType,
)
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.prompt_preparation import normalize_question
from disaster_monitor.domain.disaster import Hazard

_CURRENT_TERMS = re.compile(
    r"\b(?:recent|latest|current|today|now|news|update|updates|developments|"
    r"this week)\b",
    re.IGNORECASE,
)
_MAP_TERMS = re.compile(
    r"\b(?:map|location|where|coordinate|latitude|longitude|zoom|visible)\w*\b",
    re.IGNORECASE,
)
_HAZARD_ALIASES: dict[Hazard, tuple[str, ...]] = {
    Hazard.EARTHQUAKE: (
        "earthquake",
        "earthquakes",
        "quake",
        "quakes",
        "terremoto",
        "terremotos",
        "động đất",
        "地震",
    ),
    Hazard.TSUNAMI: ("tsunami", "tsunamis", "sóng thần", "津波"),
    Hazard.FLOOD: (
        "flood",
        "floods",
        "flooding",
        "inundación",
        "inundaciones",
        "lũ lụt",
        "洪水",
    ),
    Hazard.WILDFIRE: (
        "wildfire",
        "wildfires",
        "forest fire",
        "forest fires",
        "incendio forestal",
        "cháy rừng",
        "山火事",
    ),
    Hazard.LANDSLIDE: (
        "landslide",
        "landslides",
        "deslizamiento de tierra",
        "sạt lở đất",
        "地滑り",
    ),
    Hazard.TROPICAL_CYCLONE: (
        "typhoon",
        "typhoons",
        "hurricane",
        "hurricanes",
        "cyclone",
        "cyclones",
        "tropical cyclone",
        "tropical cyclones",
        "tifón",
        "huracán",
        "bão nhiệt đới",
        "台風",
    ),
}
_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_SLASH_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b")
_MONTH_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(20\d{2})\b",
    re.IGNORECASE,
)
_MONTHS = {
    name.lower(): index
    for index, name in enumerate(
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
_MAGNITUDE = re.compile(r"\b(?:magnitude|mag\.?|m)\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)
_COORDINATES = re.compile(
    r"(?<![\w.])(-?\d{1,3}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)(?![\w.])"
)
_EVENT_ID = re.compile(r"\b(?:us\d{6,}|jma[:_-]?[A-Za-z0-9_-]+)\b", re.I)


def _matches_alias(text: str, alias: str) -> bool:
    boundary = r"[A-Za-z0-9_]" if not alias.isascii() else r"\w"
    return bool(
        re.search(rf"(?<!{boundary}){re.escape(alias)}(?!{boundary})", text, re.I)
    )


def _extract_day(text: str) -> date | None:
    match = _ISO_DATE.search(text)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None
    match = _SLASH_DATE.search(text)
    if match:
        slash_day, slash_month, slash_year = (int(part) for part in match.groups())
        try:
            return date(slash_year, slash_month, slash_day)
        except ValueError:
            return None
    match = _MONTH_DATE.search(text)
    if match:
        month_name, month_day, month_year = match.groups()
        try:
            return date(int(month_year), _MONTHS[month_name.lower()], int(month_day))
        except ValueError:
            return None
    return None


def _calendar_range(day: date, timezone_name: str) -> tuple[datetime, datetime] | None:
    local_timezone: tzinfo
    offset = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", timezone_name)
    if offset:
        sign, hours, minutes = offset.groups()
        delta = timedelta(hours=int(hours), minutes=int(minutes))
        local_timezone = timezone(delta if sign == "+" else -delta)
    else:
        try:
            local_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return None
    start = datetime.combine(day, time.min, tzinfo=local_timezone)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _extract_coordinates(text: str) -> tuple[float | None, float | None]:
    match = _COORDINATES.search(text)
    if not match:
        return None, None
    first, second = (float(part) for part in match.groups())
    if abs(first) <= 90 and abs(second) <= 180:
        return first, second
    return None, None


class DisasterQueryParser:
    """Parse hazard/country intent once without provider or model decisions."""

    def __init__(self, country_catalog: CountryCatalog) -> None:
        self._country_catalog = country_catalog

    def parse(self, text: str) -> DisasterQueryParseResult:
        normalized = normalize_question(text)
        hazards = tuple(
            hazard
            for hazard, aliases in _HAZARD_ALIASES.items()
            if any(_matches_alias(normalized, alias) for alias in aliases)
        )
        if not hazards:
            return DisasterQueryParseResult(QueryParseStatus.NO_HAZARD)
        if len(hazards) > 1:
            return DisasterQueryParseResult(
                QueryParseStatus.MULTIPLE_HAZARDS,
                detail="More than one hazard was recognized.",
            )
        countries = self._country_catalog.find_mentions(normalized)
        if not countries:
            return DisasterQueryParseResult(QueryParseStatus.NO_COUNTRY)
        if len(countries) > 1:
            return DisasterQueryParseResult(
                QueryParseStatus.MULTIPLE_COUNTRIES,
                detail="More than one country was recognized.",
            )
        country = countries[0]
        day = _extract_day(normalized)
        date_range: tuple[datetime, datetime] | None = None
        if day is not None:
            if not country.default_timezone:
                return DisasterQueryParseResult(
                    QueryParseStatus.DATE_TIMEZONE_UNAVAILABLE,
                    detail=(
                        f"No deterministic calendar timezone is configured for "
                        f"{country.canonical_name}."
                    ),
                )
            date_range = _calendar_range(day, country.default_timezone)
            if date_range is None:
                return DisasterQueryParseResult(
                    QueryParseStatus.DATE_TIMEZONE_UNAVAILABLE,
                    detail=(
                        f"The configured calendar timezone for "
                        f"{country.canonical_name} is unavailable."
                    ),
                )
        magnitude_match = _MAGNITUDE.search(normalized)
        coordinates = _extract_coordinates(normalized)
        event_match = _EVENT_ID.search(normalized)
        prefecture_match = re.search(
            r"\b([A-Z][a-z]+(?:[- ][A-Z][a-z]+)*)\s+Prefecture\b", normalized
        )
        city_match = re.search(r"\b([A-Z][a-z]+)\s+City\b", normalized)
        query = DisasterQuery(
            hazard=hazards[0],
            country=country,
            time_intent="specified" if date_range else "recent",
            focus=("damage", "latest developments"),
            date_from=date_range[0] if date_range else None,
            date_to=date_range[1] if date_range else None,
            magnitude=float(magnitude_match.group(1)) if magnitude_match else None,
            prefecture=prefecture_match.group(1) if prefecture_match else None,
            city=city_match.group(1) if city_match else None,
            latitude=coordinates[0],
            longitude=coordinates[1],
            event_identifier=event_match.group(0) if event_match else None,
        )
        return DisasterQueryParseResult(QueryParseStatus.MATCHED, query=query)

    def classify(self, text: str) -> RequestClassification:
        normalized = normalize_question(text)
        result = self.parse(normalized)
        query = result.query
        if query is not None:
            has_discriminator = any(
                (
                    query.time_intent == "specified",
                    query.magnitude is not None,
                    query.prefecture is not None,
                    query.city is not None,
                    query.latitude is not None,
                    query.event_identifier is not None,
                )
            )
            request_type = (
                RequestType.CURRENT_DISASTER
                if _CURRENT_TERMS.search(normalized) or has_discriminator
                else RequestType.GENERAL_DISASTER
            )
            return RequestClassification(
                request_type,
                query,
                parse_status=result.status,
            )
        if result.status in {
            QueryParseStatus.MULTIPLE_COUNTRIES,
            QueryParseStatus.MULTIPLE_HAZARDS,
            QueryParseStatus.DATE_TIMEZONE_UNAVAILABLE,
        }:
            return RequestClassification(
                RequestType.AMBIGUOUS,
                None,
                parse_status=result.status,
                detail=result.detail,
            )
        if result.status == QueryParseStatus.NO_COUNTRY:
            return RequestClassification(
                RequestType.GENERAL_DISASTER,
                None,
                parse_status=result.status,
            )
        if _MAP_TERMS.search(normalized):
            return RequestClassification(RequestType.MAP_LOCATION, None)
        return RequestClassification(RequestType.AMBIGUOUS, None)
