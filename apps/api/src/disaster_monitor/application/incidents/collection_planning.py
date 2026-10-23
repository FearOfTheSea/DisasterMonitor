"""Shared acquisition windows retain independent, exact scan eligibility."""

import re
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ports.collection import CollectionProvider
from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    CollectionPartition,
    fatality_hint_needs_followup,
    lead_retrieval_priority,
)
from disaster_monitor.domain.discovery import DiscoveryArticle, ReportingInterval
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

PLAN_VERSION = "collection-v29"


def plan_collection(
    interval: ReportingInterval,
    providers: tuple[CollectionProvider, ...],
    *,
    observed_at: datetime,
) -> tuple[CollectionPartition, ...]:
    # Aligned UTC weeks permit compatible viewers to share work. Six-hour refresh
    # generations revisit late indexing, without changing a viewer's exact interval.
    span = 7 * 86400
    start = int(interval.start.timestamp()) // span * span
    generation = f"{PLAN_VERSION}:{int(observed_at.timestamp()) // 21600}"
    result = []
    historical = tuple(p for p in providers if p.supports_time_filter)
    while start <= interval.end.timestamp():
        lower = datetime.fromtimestamp(start, UTC)
        upper = lower + timedelta(days=7)
        for index in range(max((len(p.queries) for p in historical), default=0)):
            for provider in historical:
                if index < len(provider.queries):
                    result.append(
                        CollectionPartition(
                            provider.source_id,
                            provider.queries[index],
                            lower,
                            upper,
                            generation=generation,
                        )
                    )
        start += span
    # A recent RSS snapshot has no historical query contract. Share that one
    # observation across windows; publisher evidence still uses each exact interval.
    observed = int(observed_at.timestamp()) // 21600 * 21600
    lower = datetime.fromtimestamp(observed, UTC)
    for provider in providers:
        if not provider.supports_time_filter:
            result.extend(
                CollectionPartition(
                    provider.source_id,
                    query,
                    lower,
                    lower + timedelta(hours=6),
                    generation=generation,
                )
                for query in provider.queries
            )
    return tuple(result)


def plan_alternate_reports(
    work: ClaimedCollectionWork,
    providers: tuple[CollectionProvider, ...],
    *,
    observed_at: datetime,
    article: DiscoveryArticle | None = None,
) -> tuple[CollectionPartition, ...]:
    if work.alternate_depth or work.lead is None:
        return ()
    lead = work.lead
    if article is not None and not fatality_hint_needs_followup(lead, article):
        return ()
    hint = lead.discovery_hint or lead.title
    source = SourceReference(
        "acquired-lead",
        lead.publisher,
        lead.title,
        lead.canonical_url,
        None,
        None,
        observed_at,
    )
    mentions = extract_mentions(hint, source)
    anchored = next(
        (m for m in mentions if m.place and m.place.precision == "named_place"), None
    )
    if lead.search_title:
        # The index's native headline can find a different publisher when its
        # citation URL fails. It never supplies article facts or publication.
        query = " ".join(re.findall(r"[\w'-]+", lead.search_title)[:16])
    elif anchored and anchored.place:
        words = re.findall(r"[\w'-]+", anchored.place.wording)
        query = anchored.disaster.value.replace("_", " ") + ' "' + " ".join(words) + '"'
    else:
        # An acquired headline is a search hint, never verified event evidence.
        query = " ".join(re.findall(r"[\w'-]+", hint)[:12])
    if not query:
        return ()
    date_hint = lead.indexed_at or observed_at
    generation = f"{PLAN_VERSION}:{int(observed_at.timestamp()) // 21600}"
    return tuple(
        CollectionPartition(
            p.source_id,
            query,
            date_hint - timedelta(days=3),
            date_hint + timedelta(days=1),
            generation=generation,
            alternate_for=lead.canonical_url,
            priority=int(bool(lead.search_title and lead_retrieval_priority(lead))),
        )
        for p in providers
        if p.supports_alternates
    )[:1]
