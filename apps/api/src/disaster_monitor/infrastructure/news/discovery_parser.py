"""Article text, explicit publication metadata, and reported event metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
from disaster_monitor.infrastructure.news.article_metadata import (
    article_bylines,
    primary_news,
)
from disaster_monitor.infrastructure.news.flight_article_metadata import (
    FlightArticleMetadata,
)
from disaster_monitor.infrastructure.news.headline_narrative import (
    headline_owned_paragraphs,
    is_article_decoration,
    is_photograph_caption,
)
from disaster_monitor.infrastructure.news.scoped_article_publication import (
    scoped_article_publication,
)
from disaster_monitor.infrastructure.news.visible_article_publication import (
    visible_article_publication,
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
    emphasized_characters: int = 0

    @property
    def is_section_heading(self) -> bool:
        if (
            self.tag != "p"
            or not 3 <= self.characters <= 180
            or self.emphasized_characters != self.characters
        ):
            return False
        text = " ".join(self.parts).strip()
        if text.endswith((".", "!", "?", ";", ":")):
            return False
        words = re.findall(r"[^\W\d_][\w'’.-]*", text)
        meaningful = [
            word
            for word in words
            if word.casefold()
            not in {
                "a",
                "an",
                "the",
                "and",
                "or",
                "of",
                "in",
                "on",
                "to",
                "for",
                "from",
                "as",
                "at",
                "by",
                "with",
            }
        ]
        return (
            len(words) >= 3
            and bool(meaningful)
            and all(word[0].isupper() for word in meaningful)
        )

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
    result = []
    headings: set[int] = set()
    for part in parts:
        if part.block is not None and not part.block.is_narrative:
            continue
        block = part.block
        for _ in range(128):
            if block is None or block.is_section_heading:
                break
            block = block.parent
        if block is not None and block.is_section_heading and id(block) not in headings:
            headings.add(id(block))
            result.append("\n##\n## ")
        result.append(part.text)
    return result


@dataclass
class ArticleTextSection:
    article_index: int | None
    parts: list[ArticleTextPiece] = field(default_factory=list)
    primary_heading: bool = False
    main_index: int | None = None
    continuation_parent: int | None = None
    continuation_position: int = 0


@dataclass
class ArticleElement:
    tag: str
    identifier: int
    children: int = 0


@dataclass
class ArticleHeadlineAnchor:
    main_index: int
    article_index: int | None = None
    parts: list[str] = field(default_factory=list)


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.byline_metadata: list[str] = []
        self.objects: list[dict[str, Any]] = []
        self.flight_metadata = FlightArticleMetadata()
        self.main_parts: list[ArticleTextPiece] = []
        self.caption_parts: list[list[str]] = []
        self._caption_stack: list[str] = []
        self._body_stack: list[tuple[str, ArticleTextSection]] = []
        self._bodies: list[ArticleTextSection] = []
        self._articles: list[ArticleTextSection] = []
        self._article_stack: list[int] = []
        self._main_depth = 0
        self._main_sequence = 0
        self._main_stack: list[int] = []
        self._external_headings: list[ArticleHeadlineAnchor] = []
        self._external_heading: ArticleHeadlineAnchor | None = None
        self._parts_seen = 0
        self._json: list[str] | None = None
        self._hidden = 0
        self._header_depth = 0
        self._paragraph = 0
        self._excluded: list[str] = []
        self._text_blocks: list[ArticleTextBlock] = []
        self._in_link = False
        self._span_emphasis: list[bool] = []
        self._elements: list[ArticleElement] = []
        self._element_sequence = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            self.flight_metadata.start_script(values)
        if tag == "span":
            self._span_emphasis.append(
                bool(self._span_emphasis and self._span_emphasis[-1])
                or "font-weight-bold" in (values.get("class") or "").casefold().split()
            )
        void = tag in {"img", "meta", "br", "hr", "input", "link", "source", "wbr"}
        element_parent = self._elements[-1] if self._elements else None
        if element_parent is not None:
            element_parent.children += 1
        if not void:
            self._element_sequence += 1
            self._elements.append(ArticleElement(tag, self._element_sequence))
        if values.get("id") == "EndOfArticle":
            self._body_stack.clear()
        caption = is_photograph_caption(tag, values)
        if not void and (self._caption_stack or caption):
            if not self._caption_stack:
                self.caption_parts.append([])
            self._caption_stack.append(tag)
        if tag == "article":
            index = len(self._articles)
            main_index = self._main_stack[-1] if self._main_stack else None
            self._articles.append(ArticleTextSection(index, main_index=main_index))
            if (
                main_index is not None
                and self._hidden == self._header_depth
                and not self._excluded
                and not is_article_decoration(tag, values)
            ):
                for anchor in self._external_headings:
                    if anchor.main_index == main_index and anchor.article_index is None:
                        anchor.article_index = index
            self._article_stack.append(index)
        story_section = (
            tag in {"section", "div"}
            and "story-section" in (values.get("class") or "").split()
        )
        article_body = (
            story_section
            or (
                "articleBody" in (values.get("itemprop") or "").split()
                or values.get("data-article-body") == "true"
            )
            or bool(
                re.search(
                    r"(?:^|\s)(?:post-content|post_content|entry-content|article-content|story-body|"
                    r"read__content|articlebodycontent|q-content__info|content-body)(?:\s|$)",
                    values.get("class") or "",
                )
            )
        )
        if not void and (self._body_stack or article_body):
            if article_body:
                section = ArticleTextSection(
                    self._article_stack[-1] if self._article_stack else None,
                    main_index=self._main_stack[-1] if self._main_stack else None,
                    continuation_parent=element_parent.identifier
                    if story_section and element_parent is not None
                    else None,
                    continuation_position=element_parent.children
                    if element_parent
                    else 0,
                )
                self._bodies.append(section)
            else:
                section = self._body_stack[-1][1]
            self._body_stack.append((tag, section))
        excluded = is_article_decoration(tag, values)
        if (self._excluded or excluded) and not void:
            self._excluded.append(tag)
        if (
            tag in {"div", "section"}
            and "factbox" in (values.get("class") or "").split()
            and (self._article_stack or self._body_stack or self._main_depth)
            and not self._hidden
            and not self._excluded
        ):
            # Independent publisher sections reset inherited mention context.
            # An empty Markdown heading adds a boundary without inventing wording.
            self._record("\n##\n")
        if (
            tag == "h1"
            and self._article_stack
            and not self._excluded
            and self._hidden == self._header_depth
        ):
            self._articles[self._article_stack[-1]].primary_heading = True
        if (
            tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
            and not self._article_stack
            and self._main_stack
            and not self._excluded
            and self._hidden == self._header_depth
        ):
            for anchor in self._external_headings:
                if (
                    anchor.main_index == self._main_stack[-1]
                    and anchor.article_index is None
                ):
                    anchor.article_index = -1
            if tag == "h1":
                self._external_heading = ArticleHeadlineAnchor(self._main_stack[-1])
        if tag == "main":
            self._main_depth += 1
            self._main_sequence += 1
            self._main_stack.append(self._main_sequence)
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta.setdefault(key.casefold(), values["content"] or "")
                if (
                    key.casefold() in {"author", "articleauthor"}
                    and not self._article_stack
                    and not self._body_stack
                    and not self._main_depth
                    and not self._hidden
                ):
                    self.byline_metadata.append(values["content"] or "")
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
        for index in range(len(self._elements) - 1, -1, -1):
            if self._elements[index].tag == tag:
                self._elements = self._elements[:index]
                break
        if tag == "h1" and self._external_heading is not None:
            self._external_headings.append(self._external_heading)
            self._external_heading = None
        if tag == "script":
            self.flight_metadata.end_script()
        if tag == "span" and self._span_emphasis:
            self._span_emphasis.pop()
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
            if self._main_stack:
                self._main_stack.pop()
            self._external_heading = None
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
        if (
            self._external_heading is not None
            and self._hidden == self._header_depth
            and not self._excluded
        ):
            self._external_heading.parts.append(data)
        self.flight_metadata.data(data)
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
                if self._span_emphasis and self._span_emphasis[-1]:
                    block.emphasized_characters += len(data)
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

    def narrative_parts(self, headlines: tuple[str, ...] = ()) -> list[str]:
        primary = [section for section in self._articles if section.primary_heading]
        bodies = [
            section
            for section in self._bodies
            if any(p.strip() for p in _narrative(section.parts))
        ]
        normalized = {
            " ".join(value.split()).casefold() for value in headlines if value
        }
        external = [
            anchor
            for anchor in self._external_headings
            if " ".join("".join(anchor.parts).split()).casefold() in normalized
        ]
        # Explicit sibling story sections may precede unrelated article cards.
        # Join only one adjacent group owned by the matching primary main heading.
        # A different parent or any intervening element keeps groups separate.
        if (
            not primary
            and len(external) == 1
            and len(bodies) > 1
            and bodies[0].continuation_parent is not None
            and all(
                body.article_index is None
                and body.main_index == external[0].main_index
                and body.continuation_parent == bodies[0].continuation_parent
                and body.continuation_position
                == bodies[0].continuation_position + index
                for index, body in enumerate(bodies)
            )
        ):
            return [part for body in bodies for part in _narrative(body.parts)]
        anchors = [
            anchor
            for anchor in self._external_headings
            if " ".join("".join(anchor.parts).split()).casefold() in normalized
            and anchor.article_index is not None
            and 0 <= anchor.article_index < len(self._articles)
            and self._articles[anchor.article_index].main_index == anchor.main_index
        ]
        if len(anchors) > 1:
            return []
        if anchors:
            selected = anchors[0].article_index
            owned = [body for body in bodies if body.article_index == selected]
            assert selected is not None
            return (
                [part for body in owned for part in _narrative(body.parts)]
                if owned
                else _narrative(self._articles[selected].parts)
            )
        if len(primary) > 1:
            return []
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


def _publication_date(value: Any) -> tuple[datetime | None, bool]:
    if not isinstance(value, str):
        return None, False
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=UTC), True
        except ValueError:
            return None, False
    return _date(value), False


def parse_discovery_article(
    html: str,
    *,
    url: str,
    title: str,
    publisher: str,
    retrieved_at: datetime,
    indexed_at: datetime | None,
    document_url: str | None = None,
) -> DiscoveryArticle:
    parser = ArticleParser()
    parser.feed(html)
    news = primary_news(
        [*parser.objects, *parser.flight_metadata.articles(url, document_url)],
        url,
        document_url,
    )
    headline = news.get("headline")
    source_title = (
        parser.meta.get("og:title", "").strip()
        or (headline.strip() if isinstance(headline, str) else "")
        or title
    )
    source_publisher = parser.meta.get("og:site_name", "").strip() or publisher
    external_headlines = (
        (headline if isinstance(headline, str) else "", parser.meta.get("og:title", ""))
        if news or parser.meta.get("og:type", "").casefold() == "article"
        else ()
    )
    narrative = parser.narrative_parts(external_headlines)
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
    publication, day_publication = None, False
    for candidate in (
        parser.meta.get("article:published_time"),
        news.get("datePublished"),
        parser.meta.get("datepublished"),
    ):
        publication, day_publication = _publication_date(candidate)
        if publication is not None:
            break
    if publication is None:
        publication, day_publication = _publication_date(
            scoped_article_publication(html, source_title)
        )
    if publication is None:
        publication, day_publication = _publication_date(
            visible_article_publication(html, source_title, url=document_url or url)
        )
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
        bylines=article_bylines(news, parser.byline_metadata),
        photograph_captions=tuple(
            " ".join(parts).strip() for parts in parser.caption_parts if any(parts)
        ),
    )
