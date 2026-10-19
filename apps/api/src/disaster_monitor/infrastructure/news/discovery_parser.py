"""Article text, explicit publication metadata, and reported event metadata."""

import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.events import (
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
)
from disaster_monitor.domain.evidence_types import SourceReference


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.objects: list[dict[str, Any]] = []
        self.parts: list[str] = []
        self.article_parts: list[str] = []
        self.main_parts: list[str] = []
        self.body_parts: list[str] = []
        self._body_stack: list[str] = []
        self._main_depth = 0
        self._article_depth = 0
        self._json: list[str] | None = None
        self._hidden = 0
        self._paragraph = 0
        self._excluded: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        void = tag in {"img", "meta", "br", "hr", "input", "link", "source", "wbr"}
        article_body = "articleBody" in (values.get("itemprop") or "").split() or bool(
            re.search(
                r"(?:^|\s)(?:post-content|entry-content|article-content|story-body)(?:\s|$)",
                values.get("class") or "",
            )
        )
        if not void and (self._body_stack or article_body):
            self._body_stack.append(tag)
        excluded = (
            values.get("aria-hidden") == "true"
            or values.get("role") == "dialog"
            or bool(
                re.search(
                    r"(?:^|\s)(?:entry-footer|post-tags|tags-links|republish\S*|related-(?:posts|news|links)|recommended-posts|sharing\S*)(?:\s|$)",
                    values.get("class") or "",
                )
            )
        )
        if (self._excluded or excluded) and not void:
            self._excluded.append(tag)
        if tag == "article":
            self._article_depth += 1
        if tag == "main":
            self._main_depth += 1
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key.casefold()] = values["content"] or ""
        if tag in {"script", "style", "nav", "footer", "header", "aside", "textarea"}:
            self._hidden += 1
        if tag == "script" and values.get("type") == "application/ld+json":
            self._json = []
        if tag in {"p", "h1", "h2", "h3", "h4", "li"}:
            self._paragraph += 1
            if tag.startswith("h") and not self._hidden and not self._excluded:
                self.parts.append("\n## ")
                if self._article_depth:
                    self.article_parts.append("\n## ")
                if self._main_depth:
                    self.main_parts.append("\n## ")
                if self._body_stack:
                    self.body_parts.append("\n## ")
        if tag == "br" and self._body_stack and not self._hidden and not self._excluded:
            self.body_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._body_stack:
            index = len(self._body_stack) - 1 - self._body_stack[::-1].index(tag)
            self._body_stack = self._body_stack[:index]
        if tag in self._excluded:
            index = len(self._excluded) - 1 - self._excluded[::-1].index(tag)
            self._excluded = self._excluded[:index]
        if tag == "article":
            self._article_depth = max(0, self._article_depth - 1)
        if tag == "main":
            self._main_depth = max(0, self._main_depth - 1)
        if tag == "script" and self._json is not None:
            try:
                self.objects.extend(_objects(json.loads("".join(self._json))))
            except (ValueError, RecursionError):
                pass
            self._json = None
        if tag in {"script", "style", "nav", "footer", "header", "aside", "textarea"}:
            self._hidden = max(0, self._hidden - 1)
        if tag in {"p", "h1", "h2", "h3", "h4", "li"}:
            self._paragraph = max(0, self._paragraph - 1)
            self.parts.append("\n")
            if self._article_depth:
                self.article_parts.append("\n")
            if self._main_depth:
                self.main_parts.append("\n")
            if self._body_stack:
                self.body_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._json is not None:
            self._json.append(data)
        if (
            (self._paragraph or self._body_stack)
            and not self._hidden
            and not self._excluded
            and len(self.parts) < 2000
        ):
            data = " ".join(data.split())
            self.parts.append(data)
            if self._article_depth:
                self.article_parts.append(data)
            if self._main_depth:
                self.main_parts.append(data)
            if self._body_stack:
                self.body_parts.append(data)


def _objects(value: Any, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 12:
        return []
    if isinstance(value, list):
        return [obj for child in value for obj in _objects(child, depth + 1)]
    if isinstance(value, dict):
        return [
            value,
            *[obj for child in value.values() for obj in _objects(child, depth + 1)],
        ]
    return []


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def parse_discovery_article(
    html: str,
    *,
    url: str,
    title: str,
    publisher: str,
    retrieved_at: datetime,
    indexed_at: datetime | None,
) -> DiscoveryArticle:
    parser = ArticleParser()
    parser.feed(html)
    news = next(
        (
            o
            for o in parser.objects
            if o.get("@type") in ("NewsArticle", "Article", "ReportageNewsArticle")
        ),
        {},
    )
    # Only location attached to an explicit Event is usable as event geography.
    related_events = [
        obj
        for obj in _objects(news.get("about") or news.get("mainEntity"))
        if obj.get("@type") == "Event"
    ]
    event = related_events[0] if len(related_events) == 1 else {}
    location = event.get("location")
    location = location if isinstance(location, dict) else {}
    geometry = None
    geo = location.get("geo")
    if isinstance(geo, dict):
        try:
            geometry = EventGeometry(
                kind=EventGeometryKind.POINT,
                coordinates=(
                    EventCoordinate(float(geo["latitude"]), float(geo["longitude"])),
                ),
                source=SourceReference(
                    source_id="open-news",
                    publisher=publisher,
                    title=title,
                    canonical_url=url,
                    published_at=None,
                    updated_at=None,
                    retrieved_at=retrieved_at,
                ),
            )
        except (KeyError, TypeError, ValueError):
            pass
    origin = news.get("isBasedOn")
    if isinstance(origin, dict):
        origin = origin.get("@id") or origin.get("url")
    if (
        not isinstance(origin, str)
        or not origin.startswith("https://")
        or urlsplit(origin).path in ("", "/")
    ):
        origin = None
    raw_publication = parser.meta.get("article:published_time") or news.get(
        "datePublished"
    )
    day_publication = (
        isinstance(raw_publication, str) and len(raw_publication.strip()) == 10
    )
    publication = _date(raw_publication)
    if day_publication and isinstance(raw_publication, str):
        try:
            publication = datetime.fromisoformat(raw_publication).replace(tzinfo=UTC)
        except ValueError:
            pass
    source = SourceReference(
        source_id="open-news",
        publisher=publisher,
        title=title,
        canonical_url=url,
        published_at=publication,
        publication_precision="day"
        if publication and day_publication
        else "exact"
        if publication
        else "unknown",
        updated_at=_date(parser.meta.get("article:modified_time"))
        or _date(news.get("dateModified")),
        retrieved_at=retrieved_at,
    )
    return DiscoveryArticle(
        source=source,
        text="\n".join(
            " ".join(line.split())
            for line in " ".join(
                parser.body_parts or parser.article_parts or parser.main_parts
            ).splitlines()
        )[:20_000]
        or str(news.get("articleBody") or parser.meta.get("og:description") or "")[
            :20_000
        ],
        indexed_at=indexed_at,
        event_time=_date(event.get("startDate")),
        location=location.get("name")
        if isinstance(location.get("name"), str)
        else None,
        geometry=geometry,
        event_key=event.get("@id") if isinstance(event.get("@id"), str) else None,
        origin=origin if isinstance(origin, str) and origin else None,
    )
