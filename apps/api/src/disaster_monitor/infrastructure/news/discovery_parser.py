"""Article text, explicit publication metadata, and reported event metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urldefrag, urlsplit

from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.events import (
    EventCoordinate,
    EventGeometry,
    EventGeometryKind,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.news.headline_narrative import (
    headline_owned_paragraphs,
    is_article_decoration,
    is_photograph_caption,
)


@dataclass
class ArticleTextBlock:
    tag: str
    characters: int = 0
    linked_characters: int = 0
    parts: list[str] = field(default_factory=list)
    parent: ArticleTextBlock | None = None
    container: ArticleTextBlock | None = None
    preceding_characters: int = 0
    preceding_text: str = ""

    @property
    def is_narrative(self) -> bool:
        block = self
        for _ in range(128):
            if not block._owns_text():
                return False
            parent = block.parent
            if parent is None or parent.tag not in {"strong", "b"}:
                return True
            block = parent
        return False

    def _owns_text(self) -> bool:
        if self.characters > self.linked_characters:
            return True
        if self.tag not in {"strong", "b"} or self.container is None:
            return False
        owned_characters = self.container.characters - self.container.linked_characters
        if owned_characters <= 0:
            return False
        # Keep linked names, figures, inline citations and attributed sentences.
        # A trailing emphasized complete headline belongs to its linked article.
        text = " ".join(self.parts).strip()
        attributed = re.search(
            r"\b(?:said|says|reported|confirmed|according to)\s*[:,—-]?\s*$",
            self.preceding_text,
            re.I,
        )
        return bool(attributed) or not (
            self.preceding_characters > 0
            and owned_characters == self.preceding_characters
            and len(text.split()) >= 6
            and text.endswith((".", "!", "?"))
        )


@dataclass(frozen=True)
class ArticleTextPiece:
    text: str
    block: ArticleTextBlock | None


def _narrative(parts: list[ArticleTextPiece]) -> list[str]:
    return [
        part.text for part in parts if part.block is None or part.block.is_narrative
    ]


@dataclass
class ArticleTextSection:
    article_index: int | None
    parts: list[ArticleTextPiece] = field(default_factory=list)
    primary_heading: bool = False


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.objects: list[dict[str, Any]] = []
        self.main_parts: list[ArticleTextPiece] = []
        self.caption_parts: list[list[str]] = []
        self._caption_stack: list[str] = []
        self._body_stack: list[tuple[str, ArticleTextSection]] = []
        self._bodies: list[ArticleTextSection] = []
        self._articles: list[ArticleTextSection] = []
        self._article_stack: list[int] = []
        self._main_depth = 0
        self._parts_seen = 0
        self._json: list[str] | None = None
        self._hidden = 0
        self._header_depth = 0
        self._paragraph = 0
        self._excluded: list[str] = []
        self._text_blocks: list[ArticleTextBlock] = []
        self._in_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        void = tag in {"img", "meta", "br", "hr", "input", "link", "source", "wbr"}
        if values.get("id") == "EndOfArticle":
            self._body_stack.clear()
        caption = is_photograph_caption(tag, values)
        if not void and (self._caption_stack or caption):
            if not self._caption_stack:
                self.caption_parts.append([])
            self._caption_stack.append(tag)
        if tag == "article":
            index = len(self._articles)
            self._articles.append(ArticleTextSection(index))
            self._article_stack.append(index)
        article_body = (
            "articleBody" in (values.get("itemprop") or "").split()
            or values.get("data-article-body") == "true"
        ) or bool(
            re.search(
                r"(?:^|\s)(?:post-content|entry-content|article-content|story-body|"
                r"read__content|articlebodycontent)(?:\s|$)",
                values.get("class") or "",
            )
        )
        if not void and (self._body_stack or article_body):
            if article_body:
                section = ArticleTextSection(
                    self._article_stack[-1] if self._article_stack else None
                )
                self._bodies.append(section)
            else:
                section = self._body_stack[-1][1]
            self._body_stack.append((tag, section))
        excluded = is_article_decoration(tag, values)
        if (self._excluded or excluded) and not void:
            self._excluded.append(tag)
        if (
            tag == "h1"
            and self._article_stack
            and not self._excluded
            and self._hidden == self._header_depth
        ):
            self._articles[self._article_stack[-1]].primary_heading = True
        if tag == "main":
            self._main_depth += 1
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta.setdefault(key.casefold(), values["content"] or "")
        if tag in {"script", "style", "nav", "footer", "header", "aside", "textarea"}:
            self._hidden += 1
        if tag == "header":
            self._header_depth += 1
        if tag == "script" and values.get("type") == "application/ld+json":
            self._json = []
        if tag in {"p", "h1", "h2", "h3", "h4", "li"}:
            self._paragraph += 1
            self._text_blocks.append(ArticleTextBlock(tag))
            if tag.startswith("h") and not self._hidden and not self._excluded:
                self._record("\n## ")
        if tag in {"strong", "b"}:
            parent = self._text_blocks[-1] if self._text_blocks else None
            container = next(
                (
                    block
                    for block in reversed(self._text_blocks)
                    if block.tag not in {"strong", "b"}
                ),
                None,
            )
            self._text_blocks.append(
                ArticleTextBlock(
                    tag,
                    parent=parent,
                    container=container,
                    preceding_characters=(
                        container.characters - container.linked_characters
                    )
                    if container
                    else 0,
                    preceding_text=" ".join(container.parts).strip()
                    if container
                    else "",
                )
            )
        if tag == "br" and self._body_stack and not self._hidden and not self._excluded:
            self._record("\n")
        if tag == "a":
            # HTML anchors cannot nest. Starting another anchor closes the prior
            # one; a malformed menu must not mark all later reporting as linked.
            self._in_link = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._caption_stack:
            index = len(self._caption_stack) - 1 - self._caption_stack[::-1].index(tag)
            self._caption_stack = self._caption_stack[:index]
        body_tags = [frame[0] for frame in self._body_stack]
        if tag in body_tags:
            index = len(body_tags) - 1 - body_tags[::-1].index(tag)
            self._body_stack = self._body_stack[:index]
        if tag in self._excluded:
            index = len(self._excluded) - 1 - self._excluded[::-1].index(tag)
            self._excluded = self._excluded[:index]
        if tag == "article":
            if self._article_stack:
                self._article_stack.pop()
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
        if tag == "header":
            self._header_depth = max(0, self._header_depth - 1)
        if tag in {"p", "h1", "h2", "h3", "h4", "li"}:
            self._paragraph = max(0, self._paragraph - 1)
            self._record("\n")
        if tag in {"p", "h1", "h2", "h3", "h4", "li", "strong", "b"}:
            block_tags = [block.tag for block in self._text_blocks]
            if tag in block_tags:
                index = len(block_tags) - 1 - block_tags[::-1].index(tag)
                self._text_blocks = self._text_blocks[:index]
        if tag == "a":
            self._in_link = False

    def handle_data(self, data: str) -> None:
        if self._json is not None:
            self._json.append(data)
        if self._caption_stack and not self._hidden:
            self.caption_parts[-1].append(" ".join(data.split()))
        if (
            (self._paragraph or self._body_stack)
            and not self._hidden
            and not self._excluded
            and self._parts_seen < 2000
        ):
            data = " ".join(data.split())
            for block in self._text_blocks:
                block.characters += len(data)
                block.parts.append(data)
                if self._in_link:
                    block.linked_characters += len(data)
            self._record(data)

    def _record(self, text: str) -> None:
        self._parts_seen += 1
        piece = ArticleTextPiece(
            text, self._text_blocks[-1] if self._text_blocks else None
        )
        article_index = self._article_stack[-1] if self._article_stack else None
        if article_index is not None:
            self._articles[article_index].parts.append(piece)
        if self._main_depth:
            self.main_parts.append(piece)
        if self._body_stack:
            section = self._body_stack[-1][1]
            if section.article_index == article_index:
                section.parts.append(piece)

    def narrative_parts(self) -> list[str]:
        primary = [section for section in self._articles if section.primary_heading]
        if len(primary) > 1:
            return []
        bodies = [
            section
            for section in self._bodies
            if any(p.strip() for p in _narrative(section.parts))
        ]
        if primary:
            owned = [b for b in bodies if b.article_index == primary[0].article_index]
            return (
                [p for b in owned for p in _narrative(b.parts)]
                if owned
                else _narrative(primary[0].parts)
            )
        if len(bodies) == 1:
            return _narrative(bodies[0].parts)
        if len(bodies) > 1:
            return []
        if len(self._articles) == 1:
            return _narrative(self._articles[0].parts)
        # Multiple unidentified article cards cannot become one attributed report.
        return [] if self._articles else _narrative(self.main_parts)

    @property
    def has_narrative_structure(self) -> bool:
        return bool(self._articles or self._bodies or self.main_parts)


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


def _primary_news(objects: list[dict[str, Any]], url: str) -> dict[str, Any]:
    articles = []
    seen_articles: set[str] = set()
    for obj in objects:
        kind = obj.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(k in ("NewsArticle", "Article", "ReportageNewsArticle") for k in kinds):
            identity = json.dumps(obj, sort_keys=True, ensure_ascii=False)
            if identity not in seen_articles:
                seen_articles.add(identity)
                articles.append(obj)

    def identities(article: dict[str, Any]) -> set[str]:
        result = set()
        for value in (
            article.get("url"),
            article.get("@id"),
            article.get("mainEntityOfPage"),
        ):
            if isinstance(value, dict):
                value = value.get("@id") or value.get("url")
            if isinstance(value, str) and value.startswith("https://"):
                try:
                    result.add(urldefrag(value)[0])
                except ValueError:
                    pass
        return result

    matching = [
        article for article in articles if urldefrag(url)[0] in identities(article)
    ]
    if len(matching) == 1:
        return matching[0]
    if len(matching) > 1:
        # Some publishers emit a complete primary article and a second undated
        # teaser template with the same page identity. Prefer the uniquely dated
        # object only when all supplied headlines agree; conflicting clocks or
        # distinct articles remain unresolved rather than depending on order.
        dated = [
            article
            for article in matching
            if isinstance(article.get("datePublished"), str)
            and article["datePublished"].strip()
        ]
        headlines = {
            " ".join(article["headline"].split()).casefold()
            for article in matching
            if isinstance(article.get("headline"), str) and article["headline"].strip()
        }
        if len(dated) == 1 and len(headlines) <= 1:
            return dated[0]
    if len(articles) == 1 and not identities(articles[0]):
        return articles[0]
    return {}


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
    news = _primary_news(parser.objects, url)
    headline = news.get("headline")
    source_title = (
        parser.meta.get("og:title", "").strip()
        or (headline.strip() if isinstance(headline, str) else "")
        or title
    )
    source_publisher = parser.meta.get("og:site_name", "").strip() or publisher
    narrative = parser.narrative_parts()
    if not narrative and not parser.has_narrative_structure:
        narrative = [
            "\n".join(
                headline_owned_paragraphs(
                    html,
                    (
                        headline if isinstance(headline, str) else "",
                        parser.meta.get("og:title", ""),
                    ),
                )
            )
        ]
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
                    publisher=source_publisher,
                    title=source_title,
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
        publisher=source_publisher,
        title=source_title,
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
            " ".join(line.split()) for line in " ".join(narrative).splitlines()
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
        photograph_captions=tuple(
            " ".join(parts).strip() for parts in parser.caption_parts if any(parts)
        ),
    )
