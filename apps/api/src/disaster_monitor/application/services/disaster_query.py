"""Deterministic request classification and disaster-query extraction."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone

from disaster_monitor.application.disaster import DisasterQuery, RequestType
from disaster_monitor.application.services.prompt_preparation import normalize_question
from disaster_monitor.domain.errors import InvalidQuestionError

_CURRENT_TERMS = re.compile(
    r"\b(?:recent|latest|current|today|now|update|updates|developments|this week)\b",
    re.IGNORECASE,
)
_EARTHQUAKE_TERMS = re.compile(r"\b(?:earthquake|quake)\b|地震", re.IGNORECASE)
_GENERAL_DISASTER_TERMS = re.compile(
    r"\b(?:earthquake|quake|flood|flooding|typhoon|cyclone|wildfire|landslide|tsunami)\w*\b",
    re.IGNORECASE,
)
_MAP_TERMS = re.compile(
    r"\b(?:map|location|where|coordinate|latitude|longitude|zoom|visible)\w*\b",
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_SLASH_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b")
_MAGNITUDE = re.compile(r"\b(?:magnitude|mag\.?|m)\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)
_COORDINATES = re.compile(
    r"(?<![\w.])(-?\d{1,3}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)(?![\w.])"
)
_EVENT_ID = re.compile(r"\b(?:us\d{6,}|jma[:_-]?[A-Za-z0-9_-]+)\b", re.I)


@dataclass(frozen=True, slots=True)
class RequestClassification:
    """Deterministic request type and optional normalized query."""

    request_type: RequestType
    query: DisasterQuery | None


def _extract_date(text: str) -> tuple[datetime, datetime] | None:
    """Return a non-empty UTC range for the full calendar day in Japan."""
    match = _ISO_DATE.search(text)
    if match:
        try:
            day = datetime.fromisoformat(match.group(1)).date()
        except ValueError:
            return None
    else:
        match = _SLASH_DATE.search(text)
        if not match:
            return None
        day_number, month, year = (int(part) for part in match.groups())
        try:
            day = datetime(year, month, day_number).date()
        except ValueError:
            return None
    japan_timezone = timezone(timedelta(hours=9))
    start = datetime.combine(day, time.min, tzinfo=japan_timezone).astimezone(UTC)
    end = (
        datetime.combine(day, time.min, tzinfo=japan_timezone) + timedelta(days=1)
    ).astimezone(UTC)
    return start, end


def _extract_coordinates(text: str) -> tuple[float | None, float | None]:
    match = _COORDINATES.search(text)
    if not match:
        return None, None
    first, second = (float(part) for part in match.groups())
    if abs(first) <= 90 and abs(second) <= 180:
        return first, second
    return None, None


def extract_disaster_query(text: str) -> DisasterQuery | None:
    """Extract the supported earthquake/Japan shape without using the model."""
    normalized = normalize_question(text)
    earthquake = bool(_EARTHQUAKE_TERMS.search(normalized))
    japan = bool(re.search(r"\bJapan\b|日本", normalized, re.IGNORECASE))
    if not earthquake or not japan:
        return None

    date_range = _extract_date(normalized)
    magnitude_match = _MAGNITUDE.search(normalized)
    coordinates = _extract_coordinates(normalized)
    event_match = _EVENT_ID.search(normalized)
    prefecture_match = re.search(
        r"\b([A-Z][a-z]+(?:[- ][A-Z][a-z]+)*)\s+Prefecture\b",
        normalized,
    )
    city_match = re.search(r"\b([A-Z][a-z]+)\s+City\b", normalized)
    focus = ("damage", "latest developments")
    return DisasterQuery(
        hazard="earthquake",
        geography="Japan",
        country_code="JPN",
        time_intent="specified" if date_range else "recent",
        focus=focus,
        date_from=date_range[0] if date_range else None,
        date_to=date_range[1] if date_range else None,
        magnitude=float(magnitude_match.group(1)) if magnitude_match else None,
        prefecture=prefecture_match.group(1) if prefecture_match else None,
        city=city_match.group(1) if city_match else None,
        latitude=coordinates[0],
        longitude=coordinates[1],
        event_identifier=event_match.group(0) if event_match else None,
    )


def classify_request(text: str) -> RequestClassification:
    """Classify user intent with stable lexical rules before any model call."""
    try:
        normalized = normalize_question(text)
    except InvalidQuestionError:
        raise

    query = extract_disaster_query(normalized)
    has_discriminator = query is not None and any(
        (
            query.time_intent == "specified",
            query.magnitude is not None,
            query.prefecture is not None,
            query.city is not None,
            query.latitude is not None,
            query.event_identifier is not None,
        )
    )
    if query is not None and (_CURRENT_TERMS.search(normalized) or has_discriminator):
        return RequestClassification(RequestType.CURRENT_DISASTER, query)
    if _GENERAL_DISASTER_TERMS.search(normalized):
        return RequestClassification(RequestType.GENERAL_DISASTER, query)
    if _MAP_TERMS.search(normalized):
        return RequestClassification(RequestType.MAP_LOCATION, None)
    return RequestClassification(RequestType.AMBIGUOUS, None)
