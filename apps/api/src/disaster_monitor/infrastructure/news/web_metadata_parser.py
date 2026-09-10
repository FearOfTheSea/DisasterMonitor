"""Deterministic metadata-only parsers for admitted news feeds."""

from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.domain.web_collection import (
    ApprovedWebSource,
    WebAcquisitionMode,
)


def parse_web_metadata(
    source: ApprovedWebSource,
    body: bytes,
    *,
    since: datetime,
    now: datetime,
) -> tuple[NewsFeedItem, ...]:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Web source returned unsafe XML.")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError("Web source returned malformed XML.") from error
    if source.acquisition_mode is WebAcquisitionMode.RSS_ATOM:
        return _parse_rss_atom(source, root, since=since, now=now)
    return _parse_news_sitemap(source, root, since=since, now=now)


def _parse_rss_atom(
    source: ApprovedWebSource,
    root: Element,
    *,
    since: datetime,
    now: datetime,
) -> tuple[NewsFeedItem, ...]:
    records = []
    for element in root.iter():
        if _local_name(element.tag) not in {"item", "entry"}:
            continue
        title = _child_text(element, "title")
        link = _entry_link(element)
        identity = _child_text(element, "guid") or _child_text(element, "id") or link
        published_text = (
            _child_text(element, "pubDate")
            or _child_text(element, "published")
            or _child_text(element, "updated")
        )
        published_at = _publication_time(published_text)
        if not title or not link or not identity or published_at is None:
            continue
        if not source.allows_url(link) or not since <= published_at <= now:
            continue
        records.append(
            NewsFeedItem(
                external_id=identity,
                publisher=source.publisher_name,
                title=title,
                canonical_url=link,
                published_at=published_at,
                updated_at=None,
            )
        )
    return tuple(records)


def _parse_news_sitemap(
    source: ApprovedWebSource,
    root: Element,
    *,
    since: datetime,
    now: datetime,
) -> tuple[NewsFeedItem, ...]:
    records = []
    for element in root.iter():
        if _local_name(element.tag) != "url":
            continue
        link = _child_text(element, "loc")
        title = _child_text(element, "title")
        published_at = _publication_time(_child_text(element, "publication_date"))
        if not link or not title or published_at is None:
            continue
        if not source.allows_url(link) or not since <= published_at <= now:
            continue
        records.append(
            NewsFeedItem(
                external_id=link,
                publisher=source.publisher_name,
                title=title,
                canonical_url=link,
                published_at=published_at,
                updated_at=None,
            )
        )
    return tuple(records)


def _child_text(element: Element, name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def _entry_link(element: Element) -> str | None:
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        relation = child.attrib.get("rel")
        if relation not in {None, "alternate"}:
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return None


def _publication_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo is not None else None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
