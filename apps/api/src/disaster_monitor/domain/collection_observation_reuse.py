"""Bounded reuse of a retained capture for an unchanged metadata observation."""

from datetime import datetime, timedelta

from disaster_monitor.domain.discovery import DiscoveryArticle
from disaster_monitor.domain.news import NewsFeedItem

# Unchanged index metadata cannot prove the publisher body stayed unchanged.
# Reuse preserves the old capture time and expires to permit another body request.
RETAINED_OBSERVATION_MAX_AGE = timedelta(days=1)


def can_reuse_observation(
    lead: NewsFeedItem,
    retained_lead: NewsFeedItem,
    article: DiscoveryArticle,
    *,
    now: datetime,
) -> bool:
    """Routing identities and query hints do not constitute a new observation."""
    if not any((lead.published_at, lead.updated_at, lead.indexed_at)):
        return False
    fields = (
        "canonical_url",
        "publisher",
        "title",
        "search_title",
        "published_at",
        "updated_at",
        "indexed_at",
    )
    if any(getattr(lead, name) != getattr(retained_lead, name) for name in fields):
        return False
    source = article.source
    return (
        bool(article.text.strip())
        and source.published_at is not None
        and source.publication_precision != "unknown"
        and source.canonical_url == lead.canonical_url
        and article.indexed_at == lead.indexed_at
        and source.title in (lead.title, lead.search_title)
        and (lead.published_at is None or lead.published_at == source.published_at)
        and (lead.updated_at is None or lead.updated_at == source.updated_at)
        and timedelta(0) <= now - source.retrieved_at <= RETAINED_OBSERVATION_MAX_AGE
    )
