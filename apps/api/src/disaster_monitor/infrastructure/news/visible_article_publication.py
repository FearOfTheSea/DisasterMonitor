"""Bounded visible publication markers owned by the primary publisher headline."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from disaster_monitor.infrastructure.news.headline_narrative import (
    is_article_decoration,
)

_VOID = {
    "area",
    "base",
    "br",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_HIDDEN = {"script", "style", "nav", "footer", "aside", "textarea", "form"}
_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            "jan january",
            "feb february",
            "mar march",
            "apr april",
            "may",
            "jun june",
            "jul july",
            "aug august",
            "sep sept september",
            "oct october",
            "nov november",
            "dec december",
        ),
        start=1,
    )
    for name in names.split()
}


@dataclass
class _Owner:
    headings: list[str] = field(default_factory=list)
    clocks: list[tuple[str | None, str]] = field(default_factory=list)


@dataclass
class _Frame:
    tag: str
    owners: tuple[_Owner, ...]
    hidden: bool
    heading: bool = False
    clock: bool = False
    linked: bool = False
    attribute: str | None = None
    parts: list[str] = field(default_factory=list)
    characters: int = 0


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def _headline_matches(heading: str, expected: str, hostname: str) -> bool:
    if heading == expected:
        return True
    for separator in (" » ", " | "):
        if not expected.startswith(heading + separator):
            continue
        brand = unicodedata.normalize("NFKD", expected[len(heading + separator) :])
        brand = re.sub(r"[^a-z0-9]", "", brand)
        labels = {label.replace("-", "") for label in hostname.casefold().split(".")}
        if len(brand) >= 4 and brand in labels:
            return True
    return False


def _publication_value(attribute: str | None, text: str) -> str | None:
    if attribute is not None:
        value = attribute.strip()
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return date.fromisoformat(value).isoformat()
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return stamp.isoformat() if stamp.tzinfo is not None else None
        except ValueError:
            return None
    text = " ".join(text.split())
    spanish = re.fullmatch(r"Publicad[oa] el (\d{2})-(\d{2})-(\d{4})", text, re.I)
    english = re.fullmatch(
        r"(?:Posted|Published)(?: on)?\s*:\s*([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})"
        r"(?:\s+(?:at\s+)?\d{1,2}:\d{2}(?:\s*[AP]M)?(?:\s+[A-Z]{2,5})?)?",
        text,
        re.I,
    )
    try:
        if spanish:
            return date(int(spanish[3]), int(spanish[2]), int(spanish[1])).isoformat()
        if english and (month := _MONTHS.get(english[1].casefold())):
            # A named zone abbreviation does not establish an unambiguous offset.
            # The explicit publication calendar day remains usable at day precision.
            return date(int(english[3]), month, int(english[2])).isoformat()
    except ValueError:
        pass
    return None


class _VisiblePublication(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_Frame] = []
        self.owners: list[_Owner] = []
        self.nodes = 0
        self.overflow = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.overflow or tag in _VOID:
            return
        self.nodes += 1
        if self.nodes > 10_000 or len(self.stack) >= 128:
            self.overflow = True
            return
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        # Article-footer metadata may own a publication clock even though the
        # narrative parser excludes footer prose from attributed source accounts.
        decoration_attrs = {
            **values,
            "class": " ".join(c for c in classes if c != "entry-footer"),
        }
        hidden = (
            bool(self.stack and self.stack[-1].hidden)
            or tag in _HIDDEN
            or is_article_decoration(tag, decoration_attrs)
        )
        owners = self.stack[-1].owners if self.stack else ()
        if not hidden and (tag in {"article", "header"} or "content-header" in classes):
            owner = _Owner()
            self.owners.append(owner)
            owners = (owner,) if tag == "article" else (*owners, owner)
        if tag == "a":
            for frame in self.stack:
                if frame.heading:
                    frame.linked = True
        heading = tag == "h1" and not hidden
        clock = not hidden and (
            (
                tag == "time"
                and (
                    "published" in classes
                    or "datePublished" in (values.get("itemprop") or "").split()
                )
            )
            or "content-date-posted" in classes
        )
        self.stack.append(
            _Frame(
                tag,
                owners,
                hidden,
                heading=heading,
                clock=clock,
                linked=heading and any(f.tag == "a" for f in self.stack),
                attribute=values.get("datetime") if tag == "time" else None,
            )
        )

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag != tag:
                continue
            closing, self.stack = self.stack[index:], self.stack[:index]
            for frame in closing:
                if frame.hidden:
                    continue
                text = " ".join(frame.parts)
                if frame.heading and not frame.linked and frame.characters <= 600:
                    for owner in frame.owners:
                        owner.headings.append(_normalized(text))
                if frame.clock:
                    for owner in frame.owners:
                        owner.clocks.append(
                            (frame.attribute, text if frame.characters <= 256 else "")
                        )
            break

    def handle_data(self, data: str) -> None:
        if not self.stack or self.stack[-1].hidden:
            return
        for frame in self.stack:
            if frame.heading or frame.clock:
                frame.characters += len(data)
                if frame.characters <= 600:
                    frame.parts.append(data)


def visible_article_publication(html: str, headline: str, *, url: str) -> str | None:
    """Use an explicit publication marker only under one matching primary headline."""
    expected = _normalized(headline)
    hostname = urlsplit(url).hostname or ""
    if not expected:
        return None
    parser = _VisiblePublication()
    parser.feed(html)
    if parser.overflow:
        return None
    values = set()
    for owner in parser.owners:
        if (
            len(owner.headings) != 1
            or not _headline_matches(owner.headings[0], expected, hostname)
            or not owner.clocks
        ):
            continue
        for attribute, text in owner.clocks:
            value = _publication_value(attribute, text)
            if value is None:
                return None
            values.add(value)
    return next(iter(values)) if len(values) == 1 else None
