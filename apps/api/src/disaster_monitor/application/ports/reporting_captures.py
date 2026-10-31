"""Exact publisher capture identity and the consumer-owned archive read seam."""

import json
from dataclasses import asdict
from hashlib import sha256
from typing import Protocol

from disaster_monitor.domain.discovery import DiscoveryArticle


def reporting_capture_id(article: DiscoveryArticle) -> str:
    """Address captured text and attribution, including the observation clock."""
    material = json.dumps(
        [
            asdict(article.source),
            article.bylines,
            article.origin,
            article.original_url,
            article.text,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return sha256(material.encode()).hexdigest()


class ReportingCaptureReader(Protocol):
    async def read_capture(
        self, capture_id: str, *, canonical_urls: tuple[str, ...]
    ) -> DiscoveryArticle | None:
        """Read an exact observation; the caller must verify collection ownership."""
        ...
