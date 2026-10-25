"""Source-supported occurrence clocks and temporal account boundaries, without I/O."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from disaster_monitor.domain.event_mentions import MentionTime
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.mention_occurrence import (
    date_is_occurrence,
    has_later_physical_occurrence,
    occurrence_role,
    occurrence_years,
)

_MONTHS = (
    "January February March April May June July August September "
    "October November December"
).split()


MONTH_WORDING = (
    "|".join(
        name + ("|" + name[:3] + r"\.?" if len(name) > 3 else "") for name in _MONTHS
    )
    + r"|Sept\.?"
)


DAY_MONTH_DATE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:(?:[-–]|\s+to\s+)(?P<last>\d{{1,2}}))?\s+(?P<month>{MONTH_WORDING})(?:\s+(?P<year>20\d{{2}}|19\d{{2}}))?(?!\w)",
    re.I,
)


MONTH_DAY_DATE = re.compile(
    rf"\b(?P<month>{MONTH_WORDING})\s+(?P<day>\d{{1,2}})(?:,?\s+(?P<year>20\d{{2}}|19\d{{2}}))?\b",
    re.I,
)


WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()


WEEKDAY_WORDING = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")\b", re.I)

_EARLIER_PERIOD = re.compile(
    rf"\b(?P<period>(?:last|previous)\s+(?:{MONTH_WORDING}|"
    r"year|summer|winter|spring|autumn|fall))\s*,",
    re.I,
)
_LATER_CLOCK = re.compile(
    rf"^(?:yesterday\b|today\b|this\s+morning\b|last\s+night\b|"
    rf"(?:on\s+)?(?:{'|'.join(WEEKDAYS)}|\d{{1,2}}\s+(?:{MONTH_WORDING})|"
    rf"(?:{MONTH_WORDING})\s+\d{{1,2}})\b)",
    re.I,
)


@dataclass(frozen=True, slots=True)
class OccurrenceAccount:
    text: str
    separate: bool = False
    historical: bool = False
    period_wording: str | None = None


def separate_earlier_occurrence(text: str) -> tuple[OccurrenceAccount, ...]:
    """Keep a leading earlier event apart from an explicitly later physical event.

    Every part is an unchanged source span. Recovery work, statements and response
    clocks alone do not establish another physical event. Relative earlier periods
    remain wording rather than acquiring an assumed year or exact onset.
    """
    if re.match(r"^[\"'“‘]?\s*(?:After|Following)\b", text, re.I):
        for period in _EARLIER_PERIOD.finditer(text):
            earlier, later = text[: period.end()], text[period.end() :].strip()
            clock = _LATER_CLOCK.match(later)
            if (
                disasters_in_text(earlier)
                and occurrence_role(earlier) != "forecast"
                and clock is not None
                and date_is_occurrence(later, clock.start(), clock.end())
                and has_later_physical_occurrence(later)
            ):
                dates = [
                    m
                    for pattern in (DAY_MONTH_DATE, MONTH_DAY_DATE)
                    for m in pattern.finditer(earlier)
                    if date_is_occurrence(earlier, m.start(), m.end())
                ]
                wording = (
                    earlier[min(m.start() for m in dates) : period.end("period")]
                    if dates
                    else period["period"]
                )
                return (
                    OccurrenceAccount(earlier, True, True, wording),
                    OccurrenceAccount(later, True),
                )
    return (OccurrenceAccount(text),)


def _unresolved_period(text: str, matches: list[re.Match[str]]) -> MentionTime:
    return MentionTime(
        text[min(m.start() for m in matches) : max(m.end() for m in matches)]
    )


def _month_period(text: str) -> MentionTime | None:
    full_dates = [
        m.span() for p in (DAY_MONTH_DATE, MONTH_DAY_DATE) for m in p.finditer(text)
    ]
    matches = [
        match
        for match in re.finditer(
            rf"\b(?P<month>{MONTH_WORDING})\s+(?P<year>(?:19|20)\d{{2}})\b",
            text,
            re.I,
        )
        if not any(
            start <= match.start() and match.end() <= end for start, end in full_dates
        )
        and date_is_occurrence(text, match.start(), match.end())
    ]
    if not matches:
        return None
    if len({m[0].casefold() for m in matches}) > 1:
        return _unresolved_period(text, matches)
    match = matches[0]
    year = int(match["year"])
    month = next(
        i + 1
        for i, name in enumerate(_MONTHS)
        if name[:3].casefold() == match["month"][:3].casefold()
    )
    return MentionTime(
        match[0],
        datetime(year, month, 1, tzinfo=UTC),
        datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC),
        "range",
    )


def historical_occurrence(text: str, source: SourceReference) -> bool:
    month = _month_period(text)
    dated_years = (
        int(match["year"])
        for pattern in (DAY_MONTH_DATE, MONTH_DAY_DATE)
        for match in pattern.finditer(text)
        if match["year"] and date_is_occurrence(text, match.start(), match.end())
    )
    return bool(
        re.search(
            r"\b(?:historical|anniversary|years? ago|last year|"
            r"previous event|similar to)\b",
            text,
            re.I,
        )
    ) or bool(
        source.published_at
        and (
            any(int(y) < source.published_at.year for y in occurrence_years(text))
            or any(year < source.published_at.year for year in dated_years)
            or (month and month.start and month.start.year < source.published_at.year)
        )
    )


def mention_time(text: str, source: SourceReference) -> MentionTime | None:
    matches = list(DAY_MONTH_DATE.finditer(text)) + list(MONTH_DAY_DATE.finditer(text))
    matches = [m for m in matches if date_is_occurrence(text, m.start(), m.end())]
    if not matches:
        month_period = _month_period(text)
        if month_period is not None:
            return month_period
        weekdays = [
            m
            for m in WEEKDAY_WORDING.finditer(text)
            if date_is_occurrence(text, m.start(), m.end())
        ]
        if len(weekdays) == 1:
            weekday = weekdays[0]
            if re.search(r"\b(?:next|every|each)\s*$", text[: weekday.start()], re.I):
                return None
            publication = source.published_at
            if publication is None or historical_occurrence(text, source):
                return MentionTime(weekday[0])
            target = next(
                i
                for i, name in enumerate(WEEKDAYS)
                if name.casefold() == weekday[0].casefold()
            )
            days = (publication.weekday() - target) % 7
            if days == 0 and re.search(r"\blast\s*$", text[: weekday.start()], re.I):
                days = 7
            date = publication.date() - timedelta(days=days)
            if re.search(r"\blast week\b", text, re.I):
                monday = publication.date() - timedelta(days=publication.weekday())
                date = monday - timedelta(days=7) + timedelta(days=target)
            elif re.search(r"\bthis\s*$", text[: weekday.start()], re.I):
                monday = publication.date() - timedelta(days=publication.weekday())
                date = monday + timedelta(days=target)
                if date > publication.date():
                    return MentionTime(weekday[0])
            start = datetime(date.year, date.month, date.day, tzinfo=UTC)
            return MentionTime(
                weekday[0], start, start + timedelta(days=1), "day", True
            )
        approximate = re.search(
            rf"\b(?:early|mid|late)\s+(?:{MONTH_WORDING})(?:\s+20\d{{2}})?\b",
            text,
            re.I,
        )
        if approximate and date_is_occurrence(
            text, approximate.start(), approximate.end()
        ):
            return MentionTime(approximate[0])
        return None
    if len({m.group().casefold() for m in matches}) > 1:
        # Retain explicit ambiguity so later attachment cannot borrow a prior clock.
        return _unresolved_period(text, matches)
    match = matches[0]
    year = match["year"]
    publication = source.published_at
    if year is None and publication is None:
        return MentionTime(match.group())
    month = next(
        i + 1
        for i, name in enumerate(_MONTHS)
        if name[:3].casefold() == match["month"][:3].casefold()
    )
    try:
        start = datetime(
            int(year) if year else publication.year if publication else 0,
            month,
            int(match["day"]),
            tzinfo=UTC,
        )
        if year is None and publication and start > publication + timedelta(days=1):
            start = start.replace(year=start.year - 1)
        last = match.groupdict().get("last")
        end = (
            start.replace(day=int(last)) + timedelta(days=1)
            if last
            else start + timedelta(days=1)
        )
        return MentionTime(
            match.group(), start, end, "range" if last else "day", year is None
        )
    except ValueError:
        return MentionTime(match.group())
