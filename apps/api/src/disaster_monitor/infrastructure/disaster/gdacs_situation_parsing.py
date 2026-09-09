"""Parse the source-owned GDACS impact report page."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser


@dataclass(frozen=True, slots=True)
class GdacsReportObservation:
    """One row from a GDACS Sendai impact table."""

    indicator_type: str
    name: str
    value: str
    country: str
    region: str


@dataclass(frozen=True, slots=True)
class GdacsReportPageData:
    """Validated observations and explicit page-level dates."""

    observations: tuple[GdacsReportObservation, ...]
    assessed_at: datetime
    episode_start: datetime | None
    episode_end: datetime | None


@dataclass(frozen=True, slots=True)
class _EpisodeDates:
    episode_id: str
    start: datetime
    end: datetime


_ASSESSMENT_DATE = re.compile(
    r"impact\s+assess(?:e|)ment\s+as\s+of\s+"
    r"(?P<day>\d{1,2})-(?P<month>\d{1,2})-(?P<year>20\d{2})",
    re.IGNORECASE,
)
_FULL_DATE = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})\s+(?P<year>20\d{2})"
)
_MONTHS = {
    month: number
    for number, month in enumerate(
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
_SECTION_IDS = {"sendaia": "A", "sendaib": "B", "sendaic": "C"}
_EPISODE_SPAN_SUFFIXES = {
    "labelepisode": "id",
    "lepisodefromdate": "start",
    "lepisodetodate": "end",
}


def _clean(value: str) -> str:
    return " ".join(value.split())


def _date_from_parts(day: str, month: str, year: str) -> datetime | None:
    try:
        return datetime(int(year), int(month), int(day), tzinfo=UTC)
    except ValueError:
        return None


def _full_date(value: str) -> datetime | None:
    match = _FULL_DATE.fullmatch(_clean(value))
    if match is None:
        return None
    month = _MONTHS.get(match.group("month").title())
    return (
        _date_from_parts(match.group("day"), str(month), match.group("year"))
        if month is not None
        else None
    )


class _GdacsReportParser(HTMLParser):
    """Extract only Sendai rows and explicit episode dates from the page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._text: list[str] = []
        self._section: str | None = None
        self._section_depth = 0
        self._cell: list[str] | None = None
        self._row_cells: list[str] = []
        self._rows: list[tuple[str, tuple[str, ...]]] = []
        self._episode_row = False
        self._episode_fields: dict[str, str] = {}
        self._episode_fields_history: list[dict[str, str]] = []
        self._episode_span: str | None = None
        self._episode_span_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attributes = dict(attrs)
        if tag == "div":
            section = _SECTION_IDS.get((attributes.get("id") or "").casefold())
            if self._section is None and section is not None:
                self._section = section
                self._section_depth = 1
            elif self._section is not None:
                self._section_depth += 1
        if tag == "tr":
            self._episode_row = True
            self._episode_fields = {}
            if self._section is not None:
                self._row_cells = []
        if self._section is not None and tag in {"td", "th"}:
            self._cell = []
        if tag == "span" and self._episode_row:
            raw_id = (attributes.get("id") or "").casefold()
            suffix = next(
                (
                    field
                    for end, field in _EPISODE_SPAN_SUFFIXES.items()
                    if raw_id.endswith(end)
                ),
                None,
            )
            if suffix is not None:
                self._episode_span = suffix
                self._episode_span_text = []

    def handle_data(self, data: str) -> None:
        self._text.append(data)
        if self._cell is not None:
            self._cell.append(data)
        if self._episode_span is not None:
            self._episode_span_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "span" and self._episode_span is not None:
            self._episode_fields[self._episode_span] = _clean(
                "".join(self._episode_span_text)
            )
            self._episode_span = None
            self._episode_span_text = []
        if self._section is not None and tag in {"td", "th"}:
            if self._cell is not None:
                self._row_cells.append(_clean("".join(self._cell)))
            self._cell = None
        if tag == "tr":
            if self._section is not None and self._row_cells:
                self._rows.append((self._section, tuple(self._row_cells)))
            if self._episode_fields:
                self._episode_fields_history.append(dict(self._episode_fields))
            self._row_cells = []
            self._episode_row = False
            self._episode_fields = {}
            self._episode_span = None
            self._episode_span_text = []
        if tag == "div" and self._section is not None:
            self._section_depth -= 1
            if self._section_depth == 0:
                self._section = None

    def page_text(self) -> str:
        return _clean(" ".join(self._text))

    def observations(self) -> tuple[GdacsReportObservation, ...]:
        observations: list[GdacsReportObservation] = []
        for indicator_type, cells in self._rows:
            if len(cells) < 4 or cells[0].casefold().startswith("sendai indicator"):
                continue
            observations.append(
                GdacsReportObservation(
                    indicator_type,
                    cells[0].casefold(),
                    cells[1],
                    cells[2],
                    cells[3],
                )
            )
        return tuple(observations)

    def episodes(self) -> tuple[_EpisodeDates, ...]:
        episodes: list[_EpisodeDates] = []
        for fields in self._episode_fields_history:
            episode_id = fields.get("id", "")
            start = _full_date(fields.get("start", ""))
            end = _full_date(fields.get("end", ""))
            if episode_id and start is not None and end is not None and end >= start:
                episodes.append(_EpisodeDates(episode_id, start, end))
        return tuple(episodes)


def _parse_assessment_date(text: str) -> datetime | None:
    match = _ASSESSMENT_DATE.search(text)
    if match is None:
        return None
    return _date_from_parts(
        match.group("day"), match.group("month"), match.group("year")
    )


def parse_gdacs_report_page(
    html: str,
    *,
    episode_id: str | None,
    now: datetime,
) -> GdacsReportPageData | None:
    """Return source-owned observations only when page dates are explicit."""
    parser = _GdacsReportParser()
    parser.feed(html)
    parser.close()
    assessed_at = _parse_assessment_date(parser.page_text())
    if assessed_at is None or assessed_at > now:
        return None
    observations = parser.observations()
    if not observations:
        return None
    episodes = parser.episodes()
    selected = None
    if episode_id is not None:
        selected = next(
            (episode for episode in episodes if episode.episode_id == episode_id),
            None,
        )
    elif len(episodes) == 1:
        selected = episodes[0]
    return GdacsReportPageData(
        observations=observations,
        assessed_at=assessed_at,
        episode_start=selected.start if selected else None,
        episode_end=selected.end if selected else None,
    )
