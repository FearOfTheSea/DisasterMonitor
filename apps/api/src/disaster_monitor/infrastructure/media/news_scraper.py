"""No-key news discovery with registry-bounded source-page media extraction."""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from importlib.resources import files
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
from defusedxml import ElementTree

from disaster_monitor.application.media import (
    DisasterMediaCandidate,
    MediaCreditKind,
    MediaEventContext,
    MediaRightsStatus,
    RetrievedMedia,
)
from disaster_monitor.application.ports.image_metadata import image_metadata

_DISCOVERY_URL = "https://www.bing.com/news/search"
_DISCOVERY_HOSTS = frozenset({"www.bing.com"})
_GENERIC_IMAGE_MARKERS = (
    "logo",
    "default",
    "placeholder",
    "favicon",
    "sprite",
    "avatar",
)
_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class PublisherMediaPolicy:
    source_id: str
    display_name: str
    page_hosts: frozenset[str]
    asset_hosts: frozenset[str]
    priority: int
    search_preferred: bool


@dataclass(frozen=True, slots=True)
class _NewsItem:
    title: str
    description: str
    source_page_url: str
    publisher: str
    published_at: datetime
    policy: PublisherMediaPolicy


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


class NewsEventMediaProvider:
    """Discover source pages, then scrape only maintained publisher policies."""

    provider_id = "bounded-news-event-media-v1"

    def __init__(
        self,
        *,
        timeout_seconds: float,
        maximum_page_bytes: int,
        maximum_image_bytes: int,
        candidate_limit: int = 12,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._maximum_page_bytes = maximum_page_bytes
        self._maximum_image_bytes = maximum_image_bytes
        self._candidate_limit = candidate_limit
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._policies = _load_policies()
        self._by_page_host = {
            host: policy for policy in self._policies for host in policy.page_hosts
        }
        self._by_source_id = {item.source_id: item for item in self._policies}

    async def discover(
        self, context: MediaEventContext, *, now: datetime
    ) -> tuple[DisasterMediaCandidate, ...]:
        del now
        news_items: list[_NewsItem] = []
        preferred_domains = tuple(
            sorted(
                host.removeprefix("www.")
                for policy in self._policies
                if policy.search_preferred
                for host in policy.page_hosts
            )
        )
        searches = await asyncio.gather(
            *(
                self._search_feed(query)
                for query in _search_queries(context, preferred_domains)
            ),
            return_exceptions=True,
        )
        successful_searches = 0
        for result in searches:
            if isinstance(result, BaseException):
                continue
            successful_searches += 1
            news_items.extend(result)
        if successful_searches == 0:
            raise RuntimeError("All bounded event-media searches were unavailable.")
        unique = {item.source_page_url: item for item in news_items}
        ranked = sorted(
            unique.values(),
            key=lambda item: (
                item.policy.priority,
                -item.published_at.timestamp(),
                item.source_page_url,
            ),
        )[: self._candidate_limit * 3]
        candidates: list[DisasterMediaCandidate] = []
        for start in range(0, len(ranked), self._candidate_limit):
            if len(candidates) >= self._candidate_limit:
                break
            page_batch = ranked[start : start + self._candidate_limit]
            scraped = await asyncio.gather(
                *(self._scrape_item(item) for item in page_batch),
                return_exceptions=True,
            )
            candidates.extend(
                item for item in scraped if isinstance(item, DisasterMediaCandidate)
            )
        return tuple(candidates[: self._candidate_limit])

    async def retrieve(self, candidate: DisasterMediaCandidate) -> RetrievedMedia:
        policy = self._by_source_id.get(candidate.source_id)
        if policy is None:
            raise ValueError("The media candidate has no maintained source policy.")
        body, response_type = await self._bounded_get(
            candidate.image_url,
            allowed_hosts=policy.asset_hosts,
            maximum_bytes=self._maximum_image_bytes,
            accept="image/jpeg, image/png",
        )
        media_type, width, height = image_metadata(body)
        if response_type and response_type not in {
            media_type,
            "application/octet-stream",
        }:
            raise ValueError("The image response type did not match its content.")
        if width < 320 or height < 180 or width * height > 80_000_000:
            raise ValueError("The source preview dimensions are outside safe bounds.")
        return RetrievedMedia(candidate, body, media_type, width, height)

    async def _search_feed(self, query: str) -> tuple[_NewsItem, ...]:
        parameters = urlencode({"q": query, "format": "rss", "mkt": "en-US"})
        url = f"{_DISCOVERY_URL}?{parameters}"
        body, _ = await self._bounded_get(
            url,
            allowed_hosts=_DISCOVERY_HOSTS,
            maximum_bytes=self._maximum_page_bytes,
            accept="application/rss+xml, application/xml, text/xml",
        )
        return self._parse_feed(body)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _parse_feed(self, body: bytes) -> tuple[_NewsItem, ...]:
        root = ElementTree.fromstring(body)
        items: list[_NewsItem] = []
        for element in root.iter():
            if _local_name(element.tag) != "item":
                continue
            values = {
                _local_name(child.tag): (child.text or "").strip() for child in element
            }
            underlying = _underlying_page_url(values.get("link", ""))
            if underlying is None:
                continue
            host = (urlsplit(underlying).hostname or "").casefold().rstrip(".")
            policy = self._by_page_host.get(host)
            if policy is None:
                continue
            try:
                published_at = parsedate_to_datetime(values.get("pubDate", ""))
            except (TypeError, ValueError):
                continue
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            items.append(
                _NewsItem(
                    title=_clean_text(values.get("title", "")),
                    description=_clean_text(values.get("description", "")),
                    source_page_url=underlying,
                    publisher=_clean_text(values.get("Source", ""))
                    or policy.display_name,
                    published_at=published_at,
                    policy=policy,
                )
            )
        return tuple(items)

    async def _scrape_item(self, item: _NewsItem) -> DisasterMediaCandidate | None:
        body, _ = await self._bounded_get(
            item.source_page_url,
            allowed_hosts=item.policy.page_hosts,
            maximum_bytes=self._maximum_page_bytes,
            accept="text/html, application/xhtml+xml",
        )
        text = body.decode("utf-8", errors="replace")
        metadata = _article_metadata(text, item.source_page_url)
        if metadata is None:
            return None
        image_host = (
            (urlsplit(metadata.image_url).hostname or "").casefold().rstrip(".")
        )
        if image_host not in item.policy.asset_hosts:
            return None
        lowered_image_url = metadata.image_url.casefold()
        if any(marker in lowered_image_url for marker in _GENERIC_IMAGE_MARKERS):
            return None
        published_at = metadata.published_at or item.published_at
        credit = metadata.credit or item.policy.display_name
        credit_kind = metadata.credit_kind or MediaCreditKind.PUBLISHER
        candidate_material = f"{item.source_page_url}|{metadata.image_url}"
        return DisasterMediaCandidate(
            candidate_id=(
                "media-candidate:"
                f"{sha256(candidate_material.encode('utf-8')).hexdigest()[:24]}"
            ),
            provider_id=self.provider_id,
            source_id=item.policy.source_id,
            publisher=item.policy.display_name,
            source_page_url=item.source_page_url,
            image_url=metadata.image_url,
            article_title=metadata.title or item.title,
            context_text=" ".join(
                value
                for value in (
                    item.title,
                    item.description,
                    metadata.title,
                    metadata.description,
                )
                if value
            ),
            caption=metadata.caption or metadata.title or item.title,
            credit=credit,
            credit_kind=credit_kind,
            published_at=published_at,
            captured_at=metadata.captured_at,
            license_name=None,
            license_url=None,
            rights_status=MediaRightsStatus.SOURCE_PREVIEW,
            source_priority=item.policy.priority,
        )

    async def _bounded_get(
        self,
        url: str,
        *,
        allowed_hosts: frozenset[str],
        maximum_bytes: int,
        accept: str,
    ) -> tuple[bytes, str]:
        for attempt in range(2):
            try:
                return await self._bounded_get_once(
                    url,
                    allowed_hosts=allowed_hosts,
                    maximum_bytes=maximum_bytes,
                    accept=accept,
                )
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == 0:
                    continue
                raise
            except httpx.HTTPStatusError as error:
                if (
                    attempt == 0
                    and error.response.status_code in _RETRYABLE_STATUS_CODES
                ):
                    continue
                raise
        raise RuntimeError("The bounded media request exhausted its retry budget.")

    async def _bounded_get_once(
        self,
        url: str,
        *,
        allowed_hosts: frozenset[str],
        maximum_bytes: int,
        accept: str,
    ) -> tuple[bytes, str]:
        current = url
        for _ in range(4):
            _validate_url(current, allowed_hosts)
            headers = {
                "Accept": accept,
                "User-Agent": "DisasterMonitor/0.1 event-media-preview",
            }
            async with self._client.stream(
                "GET", current, headers=headers, follow_redirects=False
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("The source returned an empty redirect.")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > maximum_bytes:
                    raise ValueError("The source response exceeds its byte limit.")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > maximum_bytes:
                        raise ValueError("The source response exceeds its byte limit.")
                    chunks.append(chunk)
                response_type = response.headers.get("content-type", "")
                return b"".join(chunks), response_type.split(";", 1)[0].casefold()
        raise ValueError("The source exceeded the redirect limit.")


def _load_policies() -> tuple[PublisherMediaPolicy, ...]:
    resource = files("disaster_monitor.infrastructure.media.resources").joinpath(
        "event_media_sources.v1.json"
    )
    payload = json.loads(resource.read_text(encoding="utf-8"))
    raw_sources = cast(list[dict[str, Any]], payload["sources"])
    policies = tuple(
        PublisherMediaPolicy(
            source_id=str(item["source_id"]),
            display_name=str(item["display_name"]),
            page_hosts=frozenset(
                str(value) for value in cast(list[object], item["page_hosts"])
            ),
            asset_hosts=frozenset(
                str(value) for value in cast(list[object], item["asset_hosts"])
            ),
            priority=int(cast(int, item["priority"])),
            search_preferred=bool(item.get("search_preferred", False)),
        )
        for item in raw_sources
    )
    page_hosts = [host for item in policies for host in item.page_hosts]
    if len(page_hosts) != len(set(page_hosts)):
        raise ValueError("Event-media source policies have duplicate page hosts.")
    return policies


def _search_queries(
    context: MediaEventContext, preferred_domains: tuple[str, ...]
) -> tuple[str, ...]:
    disaster = context.disaster.value.replace("_", " ")
    location = re.sub(
        r"^\s*\d+(?:\.\d+)?\s*km\s+[A-Z-]+\s+of\s+",
        "",
        context.location,
        flags=re.IGNORECASE,
    )
    country = next((item for item in context.country_terms if len(item) >= 4), "")
    if not country and "," in location:
        country = location.rsplit(",", 1)[-1].strip()
    locality = location.split(",", 1)[0].strip()
    terms = [disaster, f'"{locality}"']
    if country and country.casefold() not in locality.casefold():
        terms.append(country)
    exact = " ".join(item for item in terms if item).strip()[:200]
    broad = " ".join(item for item in (disaster, country) if item).strip()[:200]
    preferred = (
        f"{broad} ("
        + " OR ".join(f"site:{domain}" for domain in preferred_domains)
        + ")"
        if broad and preferred_domains
        else ""
    )
    rescue = f"{broad} rescue" if broad else ""
    return tuple(
        dict.fromkeys(item[:200] for item in (exact, preferred, rescue) if item)
    )


def _underlying_page_url(value: str) -> str | None:
    try:
        target = parse_qs(urlsplit(value).query).get("url", [None])[0]
    except ValueError:
        return None
    if not target:
        return None
    parsed = urlsplit(target)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return target


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


def _validate_url(url: str, allowed_hosts: frozenset[str]) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or host not in allowed_hosts
    ):
        raise ValueError("The media request escaped its registered HTTPS hosts.")


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _clean_text(value: str) -> str:
    without_markup = re.sub(r"<[^>]+>", " ", unescape(value))
    return " ".join(without_markup.split())[:1000]
