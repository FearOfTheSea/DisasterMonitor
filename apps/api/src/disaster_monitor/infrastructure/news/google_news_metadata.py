"""Google index metadata is a route to a publisher, never article evidence."""

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from disaster_monitor.domain.collection import CollectionProviderError
from disaster_monitor.infrastructure.news.public_documents import public_document_host

ARTICLE_PREFIX = "google-article:"


def publisher_host(url: str) -> str:
    host = public_document_host(url)
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Invalid publisher destination")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.lower().removeprefix("www.")
    if not address.is_global:
        raise ValueError("Invalid publisher destination")
    return host


@dataclass(frozen=True, slots=True)
class GoogleArticleMetadata:
    identity: str
    publisher: str
    title: str
    source_root: str
    indexed_at: datetime | None
    locale: tuple[str, str, str]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,2048}", self.identity):
            raise ValueError("Invalid Google article identity")
        if (
            not self.publisher.strip()
            or not self.title.strip()
            or len(self.title) > 300
        ):
            raise ValueError("Invalid Google article metadata")
        publisher_host(self.source_root)
        if self.indexed_at is not None and self.indexed_at.tzinfo is None:
            raise ValueError("Google index time must be aware")
        if len(self.locale) != 3 or any(
            not re.fullmatch(r"[A-Za-z0-9:-]{1,20}", p) for p in self.locale
        ):
            raise ValueError("Invalid Google locale")


def google_article_id(url: str) -> str:
    if public_document_host(url) != "news.google.com":
        raise ValueError("Invalid Google article URL")
    parsed = urlsplit(url)
    if not re.fullmatch(r"/(?:rss/)?articles/[A-Za-z0-9_-]{1,2048}", parsed.path):
        raise ValueError("Invalid Google article path")
    return parsed.path.rsplit("/", 1)[-1]


def feed_articles(
    body: bytes, locale: tuple[str, str, str]
) -> tuple[GoogleArticleMetadata, ...]:
    try:
        root = ElementTree.fromstring(body)
    except (ParseError, DefusedXmlException, ValueError) as error:
        raise CollectionProviderError(
            "invalid_response", "Google RSS returned malformed XML."
        ) from error
    if root.tag != "rss" or root.find("channel") is None:
        raise CollectionProviderError(
            "invalid_response", "Google RSS returned no channel."
        )
    result: dict[str, GoogleArticleMetadata] = {}
    for item in root.findall("./channel/item")[:100]:
        source = item.find("source")
        if source is None:
            continue
        try:
            published = item.findtext("pubDate")
            stamp = parsedate_to_datetime(published) if published else None
            value = GoogleArticleMetadata(
                google_article_id(item.findtext("link") or ""),
                (source.text or "").strip()[:300],
                (item.findtext("title") or "").strip()[:300],
                source.get("url") or "",
                stamp,
                locale,
            )
        except (ValueError, TypeError, OverflowError):
            continue
        result.setdefault(value.identity, value)
    return tuple(result.values())


def article_parameters(document: str, identity: str) -> tuple[int, str]:
    class Metadata(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.values: set[tuple[int, str]] = set()

        def handle_starttag(
            self, tag: str, attrs: list[tuple[str, str | None]]
        ) -> None:
            data = dict(attrs)
            stamp, signature = data.get("data-n-a-ts"), data.get("data-n-a-sg")
            if (
                data.get("data-n-a-id") == identity
                and stamp
                and signature
                and len(stamp) <= 20
                and stamp.isdecimal()
                and len(signature) <= 4096
            ):
                self.values.add((int(stamp), signature))

    parser = Metadata()
    parser.feed(document)
    if len(parser.values) != 1:
        raise CollectionProviderError(
            "invalid_response", "Google article metadata is unavailable or conflicting."
        )
    return next(iter(parser.values))


def resolution_form(identity: str, timestamp: int, signature: str) -> bytes:
    # Google public frontend format; variable fields come only from its matching
    # public article page. No account/session data or publisher request is involved.
    context = [
        [
            "X",
            "X",
            ["X", "X"],
            None,
            None,
            1,
            1,
            "US:en",
            None,
            1,
            None,
            None,
            None,
            None,
            None,
            0,
            1,
        ],
        "X",
        "X",
        1,
        [1, 1, 1],
        1,
        1,
        None,
        0,
        0,
        None,
        0,
    ]
    operation = ["garturlreq", context, identity, timestamp, signature]
    return urlencode(
        {"f.req": json.dumps([[["Fbv4je", json.dumps(operation)]]])}
    ).encode()


def publisher_destination(body: bytes, source_root: str) -> str:
    destination = None
    try:
        for line in body.decode("utf-8").splitlines():
            if not line.startswith("["):
                continue
            for frame in json.loads(line):
                if (
                    isinstance(frame, list)
                    and len(frame) > 2
                    and frame[:2] == ["wrb.fr", "Fbv4je"]
                    and frame[2]
                ):
                    value = json.loads(frame[2])
                    if (
                        isinstance(value, list)
                        and len(value) > 1
                        and value[0] == "garturlres"
                        and isinstance(value[1], str)
                    ):
                        if destination is not None and destination != value[1]:
                            raise ValueError("Conflicting destinations")
                        destination = value[1]
        if destination is None:
            raise ValueError("No destination")
        validate_destination(destination, source_root)
    except (ValueError, TypeError, IndexError, UnicodeError) as error:
        raise CollectionProviderError(
            "invalid_response",
            "Google publisher destination is unavailable or invalid.",
        ) from error
    return destination


def validate_destination(destination: str, source_root: str) -> None:
    host, source = publisher_host(destination), publisher_host(source_root)
    if (
        (host != source and not host.endswith("." + source))
        or urlsplit(destination).path in ("", "/")
        or host == "news.google.com"
    ):
        raise ValueError("Invalid publisher destination")
