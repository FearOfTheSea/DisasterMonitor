"""Conservative narrative fallback for pages without semantic report markup."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_VOID = {
    "area",
    "base",
    "br",
    "col",
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
_HIDDEN = {"script", "style", "nav", "footer", "header", "aside", "textarea"}


def is_photograph_caption(tag: str, attrs: dict[str, str | None]) -> bool:
    return (
        tag == "figcaption"
        or "caption" in (attrs.get("itemprop") or "").split()
        or bool(
            re.search(
                r"(?:^|\s)(?:caption|image-caption|photo-caption|wp-caption-text)(?:\s|$)",
                attrs.get("class") or "",
                re.I,
            )
        )
    )


def is_article_decoration(tag: str, attrs: dict[str, str | None]) -> bool:
    """Exclude publisher interface widgets even when they contain unlinked bylines."""
    classes = attrs.get("class") or ""
    return (
        is_photograph_caption(tag, attrs)
        or "hidden" in attrs
        or attrs.get("aria-hidden") == "true"
        or attrs.get("role") == "dialog"
        or bool(
            re.search(
                r"(?:^|\s)(?:entry-footer|post-tags|tags-links|republish\S*|sharing\S*)(?:\s|$)"
                r"|(?:^|[\s_-])(?:related|recommended|recommendations|baca-juga|"
                r"also[-_]read|read[-_]also)(?:[\s_-]|$)",
                classes,
                re.I,
            )
        )
    )


@dataclass
class _Frame:
    tag: str
    hidden: bool
    article_wrapper: bool = False
    article_wrappers: int = 0
    parts: list[str] = field(default_factory=list)
    characters: int = 0
    linked_characters: int = 0
    children: list[tuple[str, str]] = field(default_factory=list)


class _HeadlineParagraphs(HTMLParser):
    def __init__(self, headlines: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self._headlines = headlines
        self._stack: list[_Frame] = []
        self._candidates: list[list[str]] = []
        self._nodes = 0
        self._characters = 0
        self._overflow = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in _VOID or self._overflow:
            return
        self._nodes += 1
        if self._nodes > 10_000 or len(self._stack) >= 128:
            self._overflow = True
            return
        self._stack.append(
            _Frame(
                tag,
                bool(self._stack and self._stack[-1].hidden)
                or tag in _HIDDEN
                or is_article_decoration(tag, values),
                article_wrapper=tag == "div"
                and "article" in (values.get("class") or "").split(),
            )
        )

    def handle_data(self, data: str) -> None:
        if self._overflow or not self._stack or self._stack[-1].hidden:
            return
        self._characters += len(data)
        if self._characters > 200_000:
            self._overflow = True
            return
        linked = False
        for frame in reversed(self._stack):
            linked = linked or frame.tag == "a"
            if frame.tag == "p" or frame.tag in _HEADINGS:
                frame.parts.append(data)
                frame.characters += len(data.strip())
                if linked:
                    frame.linked_characters += len(data.strip())
                return

    def handle_endtag(self, tag: str) -> None:
        if self._overflow:
            return
        tags = [frame.tag for frame in self._stack]
        if tag not in tags:
            return
        index = len(tags) - 1 - tags[::-1].index(tag)
        while len(self._stack) > index:
            frame = self._stack.pop()
            self._finish(frame)

    def _finish(self, frame: _Frame) -> None:
        if frame.hidden:
            return
        if self._stack and (frame.tag == "p" or frame.tag in _HEADINGS):
            text = " ".join("".join(frame.parts).split())
            if text and frame.linked_characters < frame.characters:
                self._stack[-1].children.append((frame.tag, text))
        if frame.tag not in {"div", "section", "td", "li", "body"}:
            return
        if frame.article_wrapper and self._stack:
            if any(parent.article_wrapper for parent in self._stack):
                # A nested article card cannot supply its parent's narrative.
                return
            parent = self._stack[-1]
            parent.article_wrappers += 1
            if not any(tag == "h1" for tag, _ in frame.children):
                parent.children.extend(frame.children)
                parent.children.append(("article-body-end", ""))
        if frame.article_wrappers > 1:
            return
        headings = [(tag, text) for tag, text in frame.children if tag == "h1"]
        if (
            self._stack
            and frame.tag == "div"
            and not frame.article_wrapper
            and len(headings) == 1
            and headings[0][1].casefold() in self._headlines
            and sum(tag == "p" for tag, _ in frame.children) < 2
        ):
            # A title/byline wrapper can introduce a sibling article body. Only
            # the publisher-matched heading crosses that boundary, not its text.
            self._stack[-1].children.append(headings[0])
        for index, (tag, text) in enumerate(frame.children):
            if tag != "h1" or text.casefold() not in self._headlines:
                continue
            paragraphs = []
            for child_tag, child_text in frame.children[index + 1 :]:
                if child_tag in _HEADINGS or child_tag == "article-body-end":
                    break
                paragraphs.append(child_text)
            # One paragraph may be a card teaser, even beside a matching heading.
            if len(paragraphs) >= 2:
                self._candidates.append(paragraphs)

    def narrative(self) -> list[str]:
        if self._overflow or len(self._candidates) != 1:
            return []
        return self._candidates[0]


def headline_owned_paragraphs(html: str, headlines: tuple[str, ...]) -> list[str]:
    """Read one headline's direct paragraph siblings, never arbitrary page text.

    A new sibling heading ends the fallback. Nested content, including unmarked
    photo captions and recommendation cards, cannot become narrative evidence.
    """
    normalized = {" ".join(value.split()).casefold() for value in headlines if value}
    if not normalized:
        return []
    parser = _HeadlineParagraphs(normalized)
    parser.feed(html)
    parser.close()
    return parser.narrative()
