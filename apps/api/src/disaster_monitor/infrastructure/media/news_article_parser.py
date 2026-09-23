"""Pure article HTML and metadata parsing for bounded news media discovery."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

from disaster_monitor.application.media import MediaCreditKind


@dataclass(frozen=True, slots=True)
class _Figure:
    image_url: str | None
    caption: str


@dataclass(frozen=True, slots=True)
class _ArticleMetadata:
    title: str
    description: str
    image_url: str
    caption: str
    credit: str | None
    credit_kind: MediaCreditKind | None
    published_at: datetime | None
    captured_at: datetime | None


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self.figures: list[_Figure] = []
        self._script_parts: list[str] | None = None
        self._figure_depth = 0
        self._figure_image: str | None = None
        self._caption_depth = 0
        self._caption_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.casefold(): value or "" for name, value in attrs}
        tag = tag.casefold()
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            content = values.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "script" and values.get("type", "").casefold().split(";")[0] == (
            "application/ld+json"
        ):
            self._script_parts = []
        elif tag == "figure":
            if self._figure_depth == 0:
                self._figure_image = None
                self._caption_parts = []
            self._figure_depth += 1
        elif tag == "img" and self._figure_depth > 0 and self._figure_image is None:
            self._figure_image = next(
                (
                    values.get(name)
                    for name in ("src", "data-src", "data-lazy-src")
                    if values.get(name)
                ),
                None,
            )
        elif tag == "figcaption" and self._figure_depth > 0:
            self._caption_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "script" and self._script_parts is not None:
            value = "".join(self._script_parts).strip()
            if value:
                self.json_ld.append(value)
            self._script_parts = None
        elif tag == "figcaption" and self._caption_depth > 0:
            self._caption_depth -= 1
        elif tag == "figure" and self._figure_depth > 0:
            self._figure_depth -= 1
            if self._figure_depth == 0:
                self.figures.append(
                    _Figure(
                        self._figure_image,
                        _clean_text(" ".join(self._caption_parts)),
                    )
                )

    def handle_data(self, data: str) -> None:
        if self._script_parts is not None:
            self._script_parts.append(data)
        if self._caption_depth > 0:
            self._caption_parts.append(data)


def _article_metadata(html: str, page_url: str) -> _ArticleMetadata | None:
    parser = _MetadataParser()
    parser.feed(html)
    meta = parser.meta
    title = _clean_text(meta.get("og:title", ""))
    description = _clean_text(meta.get("og:description", ""))
    image_url = meta.get("og:image:secure_url") or meta.get("og:image") or ""
    image_object, article_object = _json_ld_objects(parser.json_ld)
    if not image_url and image_object is not None:
        image_url = _object_url(image_object)
    image_url = urljoin(page_url, unescape(image_url.strip()))
    if not image_url or urlsplit(image_url).scheme != "https":
        return None

    figure = _matching_figure(parser.figures, image_url, page_url)
    caption = _clean_text(
        str((image_object or {}).get("caption", ""))
        or (figure.caption if figure is not None else "")
        or meta.get("og:image:alt", "")
        or title
    )
    credit_context = " ".join(
        value for value in (caption, figure.caption if figure else "") if value
    )
    credit, credit_kind = _credit(image_object, credit_context)
    published_at = _first_datetime(
        meta.get("article:published_time"),
        (article_object or {}).get("datePublished"),
    )
    captured_at = _first_datetime(
        (image_object or {}).get("dateCreated"),
        (image_object or {}).get("uploadDate"),
    )
    return _ArticleMetadata(
        title=title,
        description=description,
        image_url=image_url,
        caption=caption,
        credit=credit,
        credit_kind=credit_kind,
        published_at=published_at,
        captured_at=captured_at,
    )


def _json_ld_objects(
    values: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    image: dict[str, Any] | None = None
    article: dict[str, Any] | None = None
    for raw in values:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _walk_objects(payload):
            kind = item.get("@type")
            kinds = (
                {str(value) for value in kind}
                if isinstance(kind, list)
                else {str(kind)}
            )
            if image is None and "ImageObject" in kinds:
                image = item
            if article is None and kinds.intersection(
                {"NewsArticle", "Article", "ReportageNewsArticle"}
            ):
                article = item
                nested = item.get("image")
                if image is None and isinstance(nested, dict):
                    image = nested
    return image, article


def _walk_objects(value: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        item = cast(dict[str, Any], value)
        found.append(item)
        for child in item.values():
            found.extend(_walk_objects(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_objects(child))
    return found


def _object_url(value: dict[str, Any]) -> str:
    for key in ("contentUrl", "url", "thumbnailUrl"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate
    return ""


def _matching_figure(
    figures: list[_Figure], image_url: str, page_url: str
) -> _Figure | None:
    image_path = urlsplit(image_url).path.rsplit("/", 1)[-1]
    for figure in figures:
        if not figure.image_url:
            continue
        candidate = urljoin(page_url, figure.image_url)
        if candidate == image_url or (
            image_path and image_path in urlsplit(candidate).path.rsplit("/", 1)[-1]
        ):
            return figure
    return next((item for item in figures if item.caption), None)


def _credit(
    image: dict[str, Any] | None, caption: str
) -> tuple[str | None, MediaCreditKind | None]:
    if image is not None:
        credit = image.get("creditText")
        if isinstance(credit, str) and _clean_text(credit):
            return _clean_text(credit), MediaCreditKind.AGENCY
        creator = image.get("creator")
        if isinstance(creator, dict):
            name = creator.get("name")
            if isinstance(name, str) and _clean_text(name):
                return _clean_text(name), MediaCreditKind.PHOTOGRAPHER
        if isinstance(creator, str) and _clean_text(creator):
            return _clean_text(creator), MediaCreditKind.PHOTOGRAPHER
    match = re.search(
        r"(?:photo(?:graph)?(?:\s+by|\s+credit)?|image(?:\s+by)?|credit)\s*[:\-]\s*"
        r"([^()]{2,100})",
        caption,
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_text(match.group(1)), MediaCreditKind.AGENCY
    match = re.search(r"([A-Z][^.;]{2,80}\s+/\s+[^.;]{2,40})$", caption)
    if match:
        return _clean_text(match.group(1)), MediaCreditKind.AGENCY
    return None, None


def _first_datetime(*values: object) -> datetime | None:
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _clean_text(value: str) -> str:
    without_markup = re.sub(r"<[^>]+>", " ", unescape(value))
    return " ".join(without_markup.split())[:1000]
