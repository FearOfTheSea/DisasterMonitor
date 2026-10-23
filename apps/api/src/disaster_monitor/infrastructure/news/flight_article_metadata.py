"""Read inert, inline Next Flight JSON records without executing JavaScript."""

from __future__ import annotations

import json
import re
from typing import Any

from disaster_monitor.infrastructure.news.article_metadata import (
    article_identities,
    page_identities,
)

_PUSH = re.compile(
    r"(?:self\.__next_f|\(self\.__next_f=self\.__next_f\|\|\[\]\))\.push\("
)
_ROW_ID = re.compile(rb"[0-9a-f]+:", re.I)
_ROW_LENGTH = re.compile(rb"([0-9a-f]+),", re.I)
_MAX_CHARACTERS = 1_000_000
_MAX_NODES = 20_000
_MAX_DEPTH = 64


def _json_records(chunks: list[str]) -> list[Any] | None:
    """Honor byte-length text/binary rows before considering LF-framed JSON."""
    try:
        stream = "".join(chunks).encode("utf-8")
    except UnicodeEncodeError:
        return None
    position = 0
    records = []
    while position < len(stream):
        match = _ROW_ID.match(stream, position)
        if match is None or match.end() == len(stream):
            return None
        position = match.end()
        tag = stream[position]
        if tag in b"TAOoUSsLlGgMmV":
            length = _ROW_LENGTH.match(stream, position + 1)
            if length is None or len(length[1]) > 8:
                return None
            position = length.end() + int(length[1], 16)
            if position > len(stream):
                return None
            continue
        end = stream.find(b"\n", position)
        if end < 0:
            return None
        if tag in b"[{":
            try:
                records.append(json.loads(stream[position:end]))
            except (ValueError, RecursionError):
                return None
        elif tag not in b'IHEDJWNRrXxC"0123456789tfn-':
            return None
        position = end + 1
    return records


def _segments(script: str) -> list[str] | None:
    """Require the entire script to consist of the known JSON-only push calls."""
    decoder = json.JSONDecoder()
    position = 0
    result = []
    while position < len(script):
        while position < len(script) and (
            script[position].isspace() or script[position] == ";"
        ):
            position += 1
        if position == len(script):
            break
        match = _PUSH.match(script, position)
        if match is None:
            return None
        try:
            segment, position = decoder.raw_decode(script, match.end())
        except (ValueError, RecursionError):
            return None
        if position >= len(script) or script[position] != ")":
            return None
        position += 1
        if not isinstance(segment, list) or not segment or type(segment[0]) is not int:
            return None
        channel = segment[0]
        if channel == 1 and len(segment) == 2 and isinstance(segment[1], str):
            result.append(segment[1])
        elif (channel == 0 and len(segment) == 1) or (
            channel == 2 and len(segment) == 2
        ):
            continue
        else:
            # Binary/unknown channels cannot be silently removed from a stream.
            return None
    return result


def _schema_article(value: dict[str, Any]) -> bool:
    context = value.get("@context")
    contexts = context if isinstance(context, list) else [context]
    kind = value.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return any(
        c
        in (
            "https://schema.org",
            "http://schema.org",
            "https://schema.org/",
            "http://schema.org/",
        )
        for c in contexts
    ) and any(k in ("NewsArticle", "Article", "ReportageNewsArticle") for k in kinds)


class FlightArticleMetadata:
    """Bound script capture, stream decoding, and explicitly page-owned schemas."""

    def __init__(self) -> None:
        self._script: list[str] | None = None
        self._characters = 0
        self._invalid = False
        self._chunks: list[str] = []

    def start_script(self, attrs: dict[str, str | None]) -> None:
        self._script = (
            []
            if not self._invalid
            and not attrs.get("src")
            and attrs.get("type", "")
            in (None, "", "text/javascript", "application/javascript")
            else None
        )

    def data(self, data: str) -> None:
        if self._script is None:
            return
        self._characters += len(data)
        if self._characters > _MAX_CHARACTERS:
            self._invalidate()
        else:
            self._script.append(data)

    def end_script(self) -> None:
        if self._script is None:
            return
        script = "".join(self._script).strip()
        self._script = None
        if _PUSH.match(script) is None:
            return
        chunks = _segments(script)
        if chunks is None:
            self._invalidate()
        else:
            self._chunks.extend(chunks)

    def _invalidate(self) -> None:
        self._invalid = True
        self._script = None
        self._chunks.clear()

    def articles(self, url: str, document_url: str | None) -> list[dict[str, Any]]:
        if self._invalid:
            return []
        records = _json_records(self._chunks)
        if records is None:
            return []
        identities = page_identities(url, document_url)
        result = []
        nodes = 0
        for value in records:
            stack = [(value, 0)]
            while stack:
                value, depth = stack.pop()
                nodes += 1
                if nodes > _MAX_NODES or depth > _MAX_DEPTH:
                    return []
                if isinstance(value, dict):
                    if _schema_article(value) and identities & article_identities(
                        value
                    ):
                        result.append(value)
                    stack.extend((child, depth + 1) for child in value.values())
                elif isinstance(value, list):
                    stack.extend((child, depth + 1) for child in value)
        return result
