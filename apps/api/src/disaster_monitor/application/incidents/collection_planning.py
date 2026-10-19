"""Shared acquisition windows retain independent, exact scan eligibility."""

import re
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.ports.collection import CollectionProvider
from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    CollectionPartition,
)
from disaster_monitor.domain.discovery import ReportingInterval
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.mention_extraction import extract_mentions

PLAN_VERSION = "collection-v1"


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
    while start <= interval.end.timestamp():
        lower = datetime.fromtimestamp(start, UTC)
        upper = lower + timedelta(days=7)
        for index in range(max((len(p.queries) for p in providers), default=0)):
            for provider in providers:
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
    return tuple(result)


def plan_alternate_reports(
    work: ClaimedCollectionWork,
    providers: tuple[CollectionProvider, ...],
    *,
    observed_at: datetime,
) -> tuple[CollectionPartition, ...]:
    if work.alternate_depth or work.lead is None:
        return ()
    lead = work.lead
    source = SourceReference(
        "acquired-lead",
        lead.publisher,
        lead.title,
        lead.canonical_url,
        None,
        None,
        observed_at,
    )
    mentions = extract_mentions(lead.title, source)
    anchored = next(
        (m for m in mentions if m.place and m.place.precision == "named_place"), None
    )
    if anchored and anchored.place:
        words = re.findall(r"[\w'-]+", anchored.place.wording)
        query = anchored.disaster.value.replace("_", " ") + ' "' + " ".join(words) + '"'
    else:
        # An acquired headline is a search hint, never verified event evidence.
        query = " ".join(re.findall(r"[\w'-]+", lead.title)[:12])
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
        )
        for p in providers
        if p.supports_alternates
    )[:1]
