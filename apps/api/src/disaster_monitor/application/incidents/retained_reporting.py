"""Inspect exact retained publisher captures without interpreting missing passages."""

from collections.abc import Iterable
from dataclasses import dataclass

from disaster_monitor.application.incidents.discovery_report_versions import (
    publisher_article_version,
)
from disaster_monitor.application.incidents.models import ActiveIncident
from disaster_monitor.application.ports.reporting_captures import (
    ReportingCaptureReader,
)
from disaster_monitor.application.ports.reporting_captures import (
    reporting_capture_id as reporting_capture_id,
)
from disaster_monitor.domain.discovery import DiscoveryArticle

_TEXT_PAGE_SIZE = 4000


@dataclass(frozen=True, slots=True)
class RetainedReportingPage:
    capture_id: str
    article: DiscoveryArticle
    text: str
    offset: int
    total_characters: int
    next_offset: int | None
    unavailable_reason: str | None = None


async def read_retained_reporting(
    articles: tuple[DiscoveryArticle, ...],
    capture_id: str,
    *,
    reader: ReportingCaptureReader | None,
    offset: int = 0,
) -> RetainedReportingPage:
    """Resolve an archived observation only for an account owned by this view."""
    try:
        return retained_article_page(articles, capture_id, offset=offset)
    except LookupError:
        if reader is None:
            raise
    archived = await reader.read_capture(
        capture_id,
        canonical_urls=tuple(dict.fromkeys(a.source.canonical_url for a in articles)),
    )
    if archived is None or not any(
        publisher_article_version(archived) == publisher_article_version(article)
        for article in articles
    ):
        raise LookupError("This source capture is not retained in this collection.")
    # Validate the address again at the consumer boundary; never alias a newer body.
    return retained_article_page((archived,), capture_id, offset=offset)


def retained_reporting_page(
    incident: ActiveIncident, capture_id: str, *, offset: int = 0
) -> RetainedReportingPage:
    """Read only captures belonging to this retained incident; never fetch a URL."""
    reports = incident.discovery_event.reports if incident.discovery_event else ()
    return retained_article_page(
        (report.article for report in reports), capture_id, offset=offset
    )


def retained_article_page(
    articles: Iterable[DiscoveryArticle], capture_id: str, *, offset: int = 0
) -> RetainedReportingPage:
    """Read an exact capture from its owning retained collection, without I/O."""
    article = next(
        (
            article
            for article in articles
            if reporting_capture_id(article) == capture_id
        ),
        None,
    )
    if article is None:
        raise LookupError("This source capture is not retained in this collection.")
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or not 0 <= offset <= len(article.text)
    ):
        raise ValueError("Source text offset is outside this retained capture.")
    end = min(offset + _TEXT_PAGE_SIZE, len(article.text))
    return RetainedReportingPage(
        capture_id,
        article,
        article.text[offset:end],
        offset,
        len(article.text),
        end if end < len(article.text) else None,
        None
        if article.text.strip()
        else "No readable source text was retained for this capture.",
    )
