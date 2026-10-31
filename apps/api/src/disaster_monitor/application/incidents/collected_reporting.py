"""Inspect collected captures independently of hazard interpretation or association."""

from dataclasses import dataclass
from hashlib import sha256

from disaster_monitor.application.incidents.retained_reporting import (
    RetainedReportingPage,
    reporting_capture_id,
    retained_article_page,
)
from disaster_monitor.domain.discovery import (
    AssessedReport,
    DiscoveryArticle,
    DiscoveryRun,
)

_PAGE_SIZE = 25


class ReportingCatalogChanged(ValueError):
    """The client must refresh instead of paging through a changed capture set."""


@dataclass(frozen=True, slots=True)
class CollectedReportingItem:
    capture_id: str
    report: AssessedReport
    event_linked: bool


@dataclass(frozen=True, slots=True)
class CollectedReportingPage:
    items: tuple[CollectedReportingItem, ...]
    version: str
    offset: int
    total: int
    next_offset: int | None
    unlinked_only: bool


def collected_reporting_page(
    run: DiscoveryRun,
    *,
    offset: int = 0,
    version: str | None = None,
    unlinked_only: bool = True,
) -> CollectedReportingPage:
    captures: dict[DiscoveryArticle, str] = {}

    def capture(article: DiscoveryArticle) -> str:
        if article not in captures:
            captures[article] = reporting_capture_id(article)
        return captures[article]

    linked = {capture(r.article) for e in run.events for r in e.reports}
    unique: dict[str, CollectedReportingItem] = {}
    for report in run.reports:
        key = capture(report.article)
        event_linked = key in linked
        if not unlinked_only or not event_linked:
            unique.setdefault(key, CollectedReportingItem(key, report, event_linked))
    items = tuple(unique[key] for key in sorted(unique))
    state = sha256()
    for item in items:
        state.update(
            f"{item.capture_id}|{item.report.eligibility}|"
            f"{item.report.disaster}|{item.event_linked}\n".encode()
        )
    current_version = state.hexdigest()
    if isinstance(offset, bool) or not 0 <= offset <= len(items):
        raise ValueError("Collected report offset is outside the retained catalog.")
    if offset and not version:
        raise ValueError("A catalog version is required for continuation.")
    if version is not None and version != current_version:
        raise ReportingCatalogChanged(
            "Collected reporting changed. Reload the reports."
        )
    end = min(offset + _PAGE_SIZE, len(items))
    return CollectedReportingPage(
        items[offset:end],
        current_version,
        offset,
        len(items),
        end if end < len(items) else None,
        unlinked_only,
    )


def collected_reporting_text(
    run: DiscoveryRun, capture_id: str, *, offset: int = 0
) -> RetainedReportingPage:
    return retained_article_page(
        (report.article for report in run.reports), capture_id, offset=offset
    )
