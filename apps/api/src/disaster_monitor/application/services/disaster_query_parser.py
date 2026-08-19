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
from disaster_monitor.application.disaster_aliases import recognized_disasters
from disaster_monitor.application.ports.geography import CountryCatalog
from disaster_monitor.application.services.disaster_query_policy import (
    DisasterQueryPolicyRegistry,
    default_disaster_query_policies,
)
from disaster_monitor.application.services.prompt_preparation import normalize_question

_CURRENT_TERMS = re.compile(
    r"\b(?:recent|latest|current|today|now|news|update|updates|developments|"
    r"this week)\b",
    re.IGNORECASE,
)
_MAP_TERMS = re.compile(
    r"\b(?:map|location|where|coordinate|latitude|longitude|zoom|visible)\w*\b",
    re.IGNORECASE,
)
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
_COORDINATES = re.compile(
    r"(?<![\w.])(-?\d{1,3}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)(?![\w.])"
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
    """Parse disaster/country intent once without provider or model decisions."""

    def __init__(
        self,
        country_catalog: CountryCatalog,
        disaster_policies: DisasterQueryPolicyRegistry | None = None,
    ) -> None:
        self._country_catalog = country_catalog
        self._disaster_policies = disaster_policies or default_disaster_query_policies()

    def parse(self, text: str) -> DisasterQueryParseResult:
        normalized = normalize_question(text)
        disasters = recognized_disasters(normalized)
        if not disasters:
            return DisasterQueryParseResult(QueryParseStatus.NO_DISASTER)
        if len(disasters) > 1:
            return DisasterQueryParseResult(
                QueryParseStatus.MULTIPLE_DISASTERS,
                detail="More than one disaster was recognized.",
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
        coordinates = _extract_coordinates(normalized)
        prefecture_match = re.search(
            r"\b([A-Z][a-z]+(?:[- ][A-Z][a-z]+)*)\s+Prefecture\b", normalized
        )
        city_match = re.search(r"\b([A-Z][a-z]+)\s+City\b", normalized)
        query = DisasterQuery(
            disaster=disasters[0],
            country=country,
            time_intent="specified" if date_range else "recent",
            focus=("damage", "latest developments"),
            date_from=date_range[0] if date_range else None,
            date_to=date_range[1] if date_range else None,
            prefecture=prefecture_match.group(1) if prefecture_match else None,
            city=city_match.group(1) if city_match else None,
            latitude=coordinates[0],
            longitude=coordinates[1],
            event_discriminators=self._disaster_policies.for_disaster(
                disasters[0]
            ).discriminators(normalized),
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
                    query.prefecture is not None,
                    query.city is not None,
                    query.latitude is not None,
                    bool(query.event_discriminators),
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
            QueryParseStatus.MULTIPLE_DISASTERS,
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
