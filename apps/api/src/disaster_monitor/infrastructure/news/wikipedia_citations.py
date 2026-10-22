"""Bounded parsing of dated, editorial disaster-category citation links."""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlsplit

from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.public_documents import public_document_host

MONTHS = (
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
)
_VOID = {"br", "img", "meta", "link", "hr", "input", "source", "wbr"}
_GROUND_COLLAPSE_LEAD = re.compile(
    r"\b(?:mines?|quarr(?:y|ies)|open[- ]pits?)\b.{0,120}"
    r"\b(?:collaps\w*|cave[- ]ins?|bur(?:y|ied|ies))\b"
    r"|\b(?:collaps\w*|cave[- ]ins?|bur(?:y|ied|ies))\b.{0,120}"
    r"\b(?:mines?|quarr(?:y|ies)|open[- ]pits?)\b",
    re.I,
)


def _is_disaster_lead(context: str) -> bool:
    # An editorial mine-collapse summary may describe a slope failure without
    # naming its hazard. Retrieve the publisher; the index cannot classify it.
    return bool(disasters_in_text(context) or _GROUND_COLLAPSE_LEAD.search(context))


class CitationCapacityError(ValueError):
    """A citation page cannot fit the configured admission bound."""


class _CitationLeads:
    def __init__(self, revision: int, maximum: int) -> None:
        self.revision = revision
        self.maximum = maximum
        self.leads: dict[str, NewsFeedItem] = {}
        self.invalid_links = 0

    def add(
        self, url: str, context: str, indexed_day: date, search_title: str = ""
    ) -> None:
        host = public_document_host(url)
        if (
            host is None
            or urlsplit(url).path in ("", "/")
            or any(
                host == d or host.endswith("." + d)
                for d in ("wikipedia.org", "wikimedia.org")
            )
        ):
            self.invalid_links += 1
            return
        citation = sha256(url.encode()).hexdigest()[:16]
        self.leads.setdefault(
            url,
            NewsFeedItem(
                f"https://en.wikipedia.org/w/index.php?oldid={self.revision}#{indexed_day.isoformat()}:{citation}",
                host,
                "Article title unavailable",
                url,
                None,
                None,
                discovery_hint=context,
                search_title=_search_title(search_title),
            ),
        )
        if len(self.leads) > self.maximum:
            raise CitationCapacityError(
                "Citation count exceeded the page bound; page not acknowledged."
            )


def _search_title(text: str) -> str | None:
    text = " ".join(text.split())[:300]
    if len(re.findall(r"[\w'-]+", text)) < 4 or re.match(
        r"^(?:archived?\b|original\b|full text\b|retrieved\b)", text, re.I
    ):
        return None
    return text


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_Node | str"] = field(default_factory=list)


class _IndexTree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]
        self.nodes = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.nodes += 1
        if self.nodes > 50_000 or len(self.stack) >= 64:
            raise ValueError("Citation index HTML exceeded structural bounds.")
        node = _Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _walk(node: _Node, *, skip_lists: bool = False) -> Iterator[_Node]:
    yield node
    for child in node.children:
        if isinstance(child, _Node) and not (skip_lists and child.tag in ("ul", "ol")):
            yield from _walk(child, skip_lists=skip_lists)


def _text(node: _Node, *, skip_lists: bool = False) -> str:
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in {"script", "style"} and not (
            skip_lists and child.tag in {"ul", "ol"}
        ):
            parts.append(_text(child, skip_lists=skip_lists))
    return " ".join(" ".join(parts).split())


def _day(node: _Node) -> date | None:
    match = re.fullmatch(r"(\d{4})_([A-Za-z]+)_(\d{1,2})", node.attrs.get("id", ""))
    if not match or match[2] not in MONTHS:
        return None
    try:
        return date(int(match[1]), MONTHS.index(match[2]) + 1, int(match[3]))
    except ValueError:
        return None


def parse_citations(
    html: str,
    *,
    month: date,
    earliest: date,
    latest: date,
    revision: int,
    maximum_citations: int = 1000,
) -> tuple[tuple[NewsFeedItem, ...], int]:
    tree = _IndexTree()
    tree.feed(html)
    blocks = [
        n
        for n in _walk(tree.root)
        if "current-events-main" in n.attrs.get("class", "").split()
    ]
    collected = _CitationLeads(revision, maximum_citations)
    matching_days = 0

    def collect(node: _Node, context: str, indexed_day: date) -> None:
        if node.tag == "li":
            context = (context + " " + _text(node, skip_lists=True)).strip()[:2000]
            if _is_disaster_lead(context):
                for link in _walk(node, skip_lists=True):
                    if (
                        link.tag != "a"
                        or "external" not in link.attrs.get("class", "").split()
                    ):
                        continue
                    url = link.attrs.get("href", "").strip()
                    collected.add(url, context, indexed_day, _text(link))
        for child in node.children:
            if isinstance(child, _Node):
                collect(child, context, indexed_day)

    for block in blocks:
        indexed_day = _day(block)
        if indexed_day is None or (indexed_day.year, indexed_day.month) != (
            month.year,
            month.month,
        ):
            continue
        matching_days += 1
        if not earliest <= indexed_day <= latest:
            continue
        contents = [
            n
            for n in _walk(block)
            if "current-events-content" in n.attrs.get("class", "").split()
        ]
        if len(contents) != 1:
            raise ValueError("Citation index dated content structure is unavailable.")
        category = ""
        for child in contents[0].children:
            if not isinstance(child, _Node):
                continue
            if child.tag in {"p", "dt", "h3", "h4"}:
                category = _text(child).casefold()
            elif category == "disasters and accidents":
                collect(child, "", indexed_day)
    if not matching_days:
        raise ValueError("Citation index has no dated entries for the requested month.")
    return tuple(collected.leads.values()), collected.invalid_links


def _heading_identity(node: _Node) -> str:
    identity = node.attrs.get("id")
    if identity:
        return identity
    return next((n.attrs["id"] for n in _walk(node) if "id" in n.attrs), _text(node))


def _timeline_period(text: str, year: int, month: int) -> tuple[date, date] | None:
    match = re.match(
        rf"^{MONTHS[month - 1]}\s+(?P<day>\d{{1,2}})(?!\d)"
        rf"(?:\s*[-–—]\s*(?:(?P<month>{'|'.join(MONTHS)})\s+)?"
        r"(?P<last>\d{1,2})(?!\d))?(?=\s|[-–—:,]|$)",
        text,
    )
    if not match:
        return None
    try:
        first = date(year, month, int(match["day"]))
        last_month = MONTHS.index(match["month"]) + 1 if match["month"] else month
        last = date(
            year + (last_month < month),
            last_month,
            int(match["last"] or match["day"]),
        )
        return (first, last) if first <= last else None
    except ValueError:
        return None


def parse_weather_citations(
    html: str,
    *,
    year: int,
    earliest: date,
    latest: date,
    revision: int,
    maximum_citations: int = 1000,
) -> tuple[tuple[NewsFeedItem, ...], int]:
    """Resolve dated annual weather timeline references to external publishers.

    Statistics, other sections, undated paragraphs and internal event pages are
    not acquisition sources. Calendar dates only bound index selection.
    """
    tree = _IndexTree()
    tree.feed(html)
    references = _reference_nodes(tree.root)
    collected = _CitationLeads(revision, maximum_citations)
    in_timeline = False
    month = None
    dated_entries = 0
    for node in _walk(tree.root):
        if node.tag == "h2":
            in_timeline = _heading_identity(node) == "Timeline"
            month = None
        elif in_timeline and node.tag == "h3":
            identity = _heading_identity(node)
            month = MONTHS.index(identity) + 1 if identity in MONTHS else None
        elif in_timeline and month and node.tag == "li":
            context = _text(node, skip_lists=True)[:2000]
            period = _timeline_period(context, year, month)
            if period is None:
                continue
            dated_entries += 1
            first, last = period
            if first > latest or last < earliest or not _is_disaster_lead(context):
                continue
            _collect_references(
                _walk(node, skip_lists=True), references, collected, context, first
            )
    if not dated_entries:
        raise ValueError("Weather citation index has no dated timeline entries.")
    return tuple(collected.leads.values()), collected.invalid_links


def parse_earthquake_citations(
    html: str,
    *,
    year: int,
    earliest: date,
    latest: date,
    revision: int,
    maximum_citations: int = 1000,
) -> tuple[tuple[NewsFeedItem, ...], int]:
    """Read references from recent rows in the annual earthquake calendar.

    The table's dates, places, magnitudes and losses remain editorial hints.
    Statistics and internal event links never become publisher evidence.
    """
    tree = _IndexTree()
    tree.feed(html)
    references = _reference_nodes(tree.root)
    collected = _CitationLeads(revision, maximum_citations)
    in_calendar = False
    month = None
    dated_entries = 0
    for node in _walk(tree.root):
        if node.tag == "h2":
            in_calendar = _heading_identity(node) == "By_month"
            month = None
        elif in_calendar and node.tag == "h3":
            identity = _heading_identity(node)
            month = MONTHS.index(identity) + 1 if identity in MONTHS else None
        elif in_calendar and month and node.tag == "table":
            rows = tuple(_table_rows(node))
            if not rows:
                continue
            headings = [
                _text(cell)
                for cell in rows[0].children
                if isinstance(cell, _Node) and cell.tag == "th"
            ]
            if headings[:2] != ["Date", "Country and location"] or not {
                "M",
                "Notes",
                "Casualties",
            } <= set(headings):
                continue
            for row in rows[1:]:
                cells = [
                    cell
                    for cell in row.children
                    if isinstance(cell, _Node) and cell.tag == "td"
                ]
                if not cells:
                    continue
                day = re.match(r"^(\d{1,2})(?=\s*\[|\s*$)", _text(cells[0]))
                if day is None:
                    continue
                try:
                    indexed_day = date(year, month, int(day[1]))
                except ValueError:
                    continue
                dated_entries += 1
                if not earliest <= indexed_day <= latest:
                    continue
                context = "Earthquake editorial index: " + _text(row)[:1900]
                _collect_references(
                    _walk(row), references, collected, context, indexed_day
                )
    if not dated_entries:
        raise ValueError("Quake citation index has no recognized dated calendar rows.")
    return tuple(collected.leads.values()), collected.invalid_links


def _table_rows(table: _Node) -> Iterator[_Node]:
    """Ignore any nested table inside a calendar cell."""
    for child in table.children:
        if isinstance(child, _Node):
            if child.tag == "tr":
                yield child
            elif child.tag in {"tbody", "thead", "tfoot"}:
                yield from _table_rows(child)


def _collect_references(
    links: Iterator[_Node],
    references: dict[str, list[_Node]],
    collected: _CitationLeads,
    context: str,
    indexed_day: date,
) -> None:
    for link in links:
        target = link.attrs.get("href", "")
        if link.tag != "a" or not target.startswith("#cite_note-"):
            continue
        candidates = references.get(target[1:], [])
        if len(candidates) != 1:
            collected.invalid_links += 1
            continue
        for reference in _walk(candidates[0]):
            if (
                reference.tag == "a"
                and "external" in reference.attrs.get("class", "").split()
            ):
                collected.add(
                    reference.attrs.get("href", ""),
                    context,
                    indexed_day,
                    _text(reference),
                )


def _reference_nodes(root: _Node) -> dict[str, list[_Node]]:
    references: dict[str, list[_Node]] = {}
    for node in _walk(root):
        identity = node.attrs.get("id", "")
        if node.tag == "li" and identity.startswith("cite_note-"):
            references.setdefault(identity, []).append(node)
    return references
