"""Complementary humanitarian reporting via an explicitly configured ReliefWeb API.

This adapter supplies articles to the existing publication-window assessment. The
editorial catalog is complementary coverage, never a universal publisher gate.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from disaster_monitor.application.ports.provider_text import sanitize_provider_text
from disaster_monitor.domain.discovery import (
    AcquisitionAudit,
    DiscoveryArticle,
    DiscoveryBatch,
    ReportingInterval,
)
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.news.discovery_parser import _date
from disaster_monitor.infrastructure.news.request_schedule import (
    NewsRequestError,
    ScheduledNewsJson,
)

_CATEGORIES = (
    "Earthquake",
    "Flood",
    "Wild Fire",
    "Land Slide",
    "Drought",
    "Tropical Cyclone",
    "Volcano",
)
_FIELDS = ("title", "url", "body", "date", "source", "disaster", "primary_country")


class ReliefWebDiscoveryFeed:
    source_id = "reliefweb-discovery"
    endpoint = "https://api.reliefweb.int/v2/reports"

    def __init__(
        self,
        *,
        app_name: str | None,
        client: httpx.AsyncClient | None = None,
        maximum_records: int = 20,
        maximum_pages: int = 2,
        timeout_seconds: float = 15,
        minimum_request_interval: float = 1,
    ) -> None:
        self._app_name = (app_name or "").strip()
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds, trust_env=False
        )
        self._owns_client = client is None
        self._limit = maximum_records
        self._pages = maximum_pages
        self._schedule = ScheduledNewsJson(
            self._client,
            minimum_interval=minimum_request_interval,
            timeout_seconds=timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._schedule.aclose()
        if self._owns_client:
            await self._client.aclose()

    async def discover(
        self, *, interval: ReportingInterval
    ) -> AsyncIterator[DiscoveryBatch]:
        if not self._app_name or self._app_name.lower() in {
            "disaster-monitor-local",
            "change-me",
            "your-app-name",
        }:
            yield DiscoveryBatch(
                failed_operations=1,
                issues=(
                    "ReliefWeb complementary discovery requires an approved "
                    "configured appname; open search remains available.",
                ),
            )
            return
        seen: set[str] = set()
        # Breadth first: category coverage precedes additional pages.
        pending = [(category, 0) for category in _CATEGORIES]
        while pending:
            category, page = pending.pop(0)
            params = {
                "appname": self._app_name,
                "filter[operator]": "AND",
                "filter[conditions][0][field]": "disaster_type.name",
                "filter[conditions][0][value]": category,
                "filter[conditions][1][field]": "date.original",
                "filter[conditions][1][value][from]": interval.start.isoformat(
                    timespec="seconds"
                ),
                "filter[conditions][1][value][to]": (
                    interval.end + timedelta(seconds=1)
                ).isoformat(timespec="seconds"),
                "sort[]": "date.original:desc",
                "limit": str(self._limit),
                "offset": str(page * self._limit),
                **{f"fields[include][{i}]": field for i, field in enumerate(_FIELDS)},
            }
            try:
                snapshot = await self._schedule.get(self.endpoint, params)
                payload = snapshot.payload
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("data"), list
                ):
                    raise ValueError("Invalid report list")
                articles = []
                invalid = duplicates = 0
                for item in payload["data"]:
                    article = _article(item, retrieved_at=snapshot.retrieved_at)
                    if article is None:
                        invalid += 1
                    elif article.source.canonical_url in seen:
                        duplicates += 1
                    else:
                        articles.append(article)
                        seen.add(article.source.canonical_url)
                total = payload.get("totalCount")
                has_more = (
                    isinstance(total, int) and total > (page + 1) * self._limit
                ) or (total is None and len(payload["data"]) >= self._limit)
                truncated = has_more and page + 1 >= self._pages
                if has_more and not truncated:
                    pending.append((category, page + 1))
                issues = []
                if invalid:
                    issues.append(
                        f"ReliefWeb {category}: {invalid} malformed reports excluded."
                    )
                if truncated:
                    issues.append(
                        f"ReliefWeb {category}: page budget reached; "
                        "additional reports uncollected."
                    )
                yield DiscoveryBatch(
                    articles=tuple(articles),
                    successful_operations=1,
                    truncated=truncated,
                    issues=tuple(issues),
                    acquisition=(
                        AcquisitionAudit(
                            provider=self.source_id,
                            partition=f"{category} page {page + 1}",
                            leads_received=len(payload["data"]),
                            invalid_leads=invalid,
                            duplicate_urls=duplicates,
                        ),
                    ),
                )
            except NewsRequestError as error:
                yield DiscoveryBatch(
                    failed_operations=1,
                    issues=(
                        f"ReliefWeb {category}: {error}; "
                        f"{len(pending)} partitions unattempted. "
                        "Available reporting retained.",
                    ),
                )
                if error.http_status == 408 and error.retry_after_seconds is None:
                    continue
                return
            except (ValueError, TypeError):
                yield DiscoveryBatch(
                    failed_operations=1,
                    issues=(
                        f"ReliefWeb {category}: malformed response; "
                        "other partitions continue.",
                    ),
                )


def _article(item: Any, *, retrieved_at: datetime) -> DiscoveryArticle | None:
    if not isinstance(item, dict) or not isinstance(item.get("fields"), dict):
        return None
    fields = item["fields"]
    title, url = fields.get("title"), fields.get("url")
    if not isinstance(title, str) or not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "reliefweb.int"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        return None
    dates = fields.get("date")
    dates = dates if isinstance(dates, dict) else {}
    sources = fields.get("source")
    sources = sources if isinstance(sources, list) else []
    names = [
        source["name"]
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("name"), str)
    ]
    body = fields.get("body")
    text = sanitize_provider_text(body, limit=20_000) if isinstance(body, str) else ""
    country = fields.get("primary_country")
    country = country if isinstance(country, dict) else {}
    publication = _date(dates.get("original"))
    notices = [
        "ReliefWeb-supplied report text; source link retained."
        if text
        else "ReliefWeb supplied metadata but no report text; source link retained.",
        "Country is report context, not a damage boundary.",
    ]
    if publication and not any(
        (
            publication.hour,
            publication.minute,
            publication.second,
            publication.microsecond,
        )
    ):
        notices.append(
            "Original publication is provider-supplied at midnight; "
            "this may represent date precision rather than a known exact time."
        )
    if isinstance(body, str) and len(body) > 20_000:
        notices.append("Text truncated at 20,000 characters.")
    # Taxonomy country context is never a point, affected polygon, or event onset.
    return DiscoveryArticle(
        source=SourceReference(
            source_id="reliefweb-discovery",
            publisher="; ".join(names) or "ReliefWeb (origin unknown)",
            title=title,
            canonical_url=url,
            published_at=publication,
            updated_at=_date(dates.get("changed")),
            retrieved_at=retrieved_at,
        ),
        text=text,
        indexed_at=_date(dates.get("created")),
        location=country.get("name") if isinstance(country.get("name"), str) else None,
        access_issue=" ".join(notices),
        # Each report URL remains separate unless explicit physical identity is
        # supplied by a source. A broad disaster taxonomy tag is insufficient.
    )
