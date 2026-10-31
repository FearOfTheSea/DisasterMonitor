"""Retain changed publisher accounts while deduplicating repeated observations."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from disaster_monitor.domain.discovery import (
    AssessedReport,
    DiscoveryArticle,
    ReportingInterval,
    assess_article,
)

_OBSERVATION_CLOCK = datetime(1970, 1, 1, tzinfo=UTC)


def publisher_article_version(article: DiscoveryArticle) -> DiscoveryArticle:
    """Separate a publisher account from repeated observations of that account."""
    # Index sightings, retrieval clocks and snapshot pointers are observation
    # metadata. Changed publisher clocks, text, authors and origins are versions.
    return replace(
        article,
        source=replace(
            article.source, retrieved_at=_OBSERVATION_CLOCK, snapshot_id=None
        ),
        indexed_at=None,
    )


async def assess_article_versions(
    articles: tuple[DiscoveryArticle, ...],
    retained: tuple[AssessedReport, ...],
    interval: ReportingInterval,
    *,
    country_names: frozenset[str],
) -> tuple[AssessedReport, ...]:
    by_url: dict[str, dict[DiscoveryArticle, DiscoveryArticle]] = {}
    for article in sorted(articles, key=lambda a: a.source.retrieved_at):
        by_url.setdefault(article.source.canonical_url, {})[
            publisher_article_version(article)
        ] = article
    previous = {publisher_article_version(r.article): r for r in retained}
    reports = []
    for versions in by_url.values():
        # Association retains the newest instance of identical mention wording.
        # Changed accounts remain separate, including an out-of-window republication.
        for article in sorted(
            versions.values(), key=lambda a: a.source.retrieved_at, reverse=True
        ):
            old = previous.get(publisher_article_version(article))
            reports.append(
                old
                if old is not None and old.article == article
                else await asyncio.to_thread(
                    assess_article, article, interval, country_names=country_names
                )
            )
    return tuple(reports)
