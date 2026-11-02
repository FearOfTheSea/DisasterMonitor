"""Explicit publication microdata owned by the primary article and its headline."""

from dataclasses import dataclass, field
from html.parser import HTMLParser

from disaster_monitor.infrastructure.news.headline_narrative import (
    is_article_decoration,
)

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
_HIDDEN = {"script", "style", "nav", "aside", "footer", "textarea", "form"}
_TYPES = {
    f"{scheme}://schema.org/{kind}"
    for scheme in ("http", "https")
    for kind in ("Article", "NewsArticle", "ReportageNewsArticle")
}


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass
class _Article:
    headings: list[str] = field(default_factory=list)
    named_headlines: list[str] = field(default_factory=list)
    clocks: list[str] = field(default_factory=list)


@dataclass
class _Frame:
    tag: str
    article: _Article | None
    hidden: bool
    heading: bool = False
    linked: bool = False
    characters: int = 0
    parts: list[str] = field(default_factory=list)


class _ArticlePublication(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_Frame] = []
        self.articles: list[_Article] = []
        self.nodes = 0
        self.overflow = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.overflow:
            return
        self.nodes += 1
        if self.nodes > 10_000 or len(self.stack) >= 128:
            self.overflow = True
            return
        values = dict(attrs)
        hidden = (
            bool(self.stack and self.stack[-1].hidden)
            or tag in _HIDDEN
            or is_article_decoration(tag, values)
        )
        owner = self.stack[-1].article if self.stack else None
        if "itemscope" in values:
            # Every nested item starts its own scope, including author, image,
            # publisher and related articles. None can lend a date to its parent.
            owner = None
            if not hidden and _TYPES.intersection(
                (values.get("itemtype") or "").split()
            ):
                owner = _Article()
                self.articles.append(owner)
        if not hidden and owner is not None and "itemscope" not in values:
            properties = (values.get("itemprop") or "").split()
            if tag == "meta":
                if "datePublished" in properties:
                    owner.clocks.append((values.get("content") or "").strip())
                if "headline" in properties:
                    owner.named_headlines.append(
                        _normalized(values.get("content") or "")
                    )
            elif tag == "time" and "datePublished" in properties:
                owner.clocks.append((values.get("datetime") or "").strip())
        if tag == "a":
            for frame in self.stack:
                if frame.heading:
                    frame.linked = True
        if tag not in _VOID:
            self.stack.append(
                _Frame(
                    tag,
                    owner,
                    hidden,
                    heading=tag == "h1" and not hidden,
                    linked=any(frame.tag == "a" for frame in self.stack),
                )
            )

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag != tag:
                continue
            closing, self.stack = self.stack[index:], self.stack[:index]
            for frame in closing:
                if (
                    frame.heading
                    and not frame.linked
                    and frame.article is not None
                    and frame.characters <= 600
                ):
                    frame.article.headings.append(_normalized(" ".join(frame.parts)))
            break

    def handle_data(self, data: str) -> None:
        if not self.stack or self.stack[-1].hidden:
            return
        for frame in self.stack:
            if frame.heading:
                frame.characters += len(data)
                if frame.characters <= 600:
                    frame.parts.append(data)


def scoped_article_publication(html: str, headline: str) -> str | None:
    """Keep one agreeing explicit clock under an exact, unlinked primary h1."""
    expected = _normalized(headline)
    if not expected:
        return None
    parser = _ArticlePublication()
    parser.feed(html)
    if parser.overflow:
        return None
    clocks = set()
    for article in parser.articles:
        if article.headings != [expected]:
            continue
        if any(value != expected for value in article.named_headlines):
            continue
        clocks.update(article.clocks)
    return next(iter(clocks)) if len(clocks) == 1 else None
