"""Shared acquisition windows retain independent, exact scan eligibility."""

import re
from datetime import UTC, datetime, timedelta

from disaster_monitor.application.incidents.collection_index_planning import (
    plan_index_collection,
)
from disaster_monitor.application.ports.collection import (
    CollectionProvider,
    ImmutableIndexProvider,
)
from disaster_monitor.domain.collection import (
    ClaimedCollectionWork,
    CollectionPartition,
    fatality_hint_needs_followup,
    search_acquisition_priority,
)
from disaster_monitor.domain.discovery import DiscoveryArticle, ReportingInterval
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.domain.hazards.news_classification import disasters_in_text
from disaster_monitor.domain.mention_extraction import extract_mentions

PLAN_VERSION = "collection-v114"


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
    # A maintained directory can refresh between calls, but one plan must retain
    # one immutable query ordering while its aligned windows are assembled.
    historical = tuple(
        (p, p.queries)
        for p in providers
        if p.supports_time_filter and not isinstance(p, ImmutableIndexProvider)
    )
    while start <= interval.end.timestamp():
        lower = datetime.fromtimestamp(start, UTC)
        upper = lower + timedelta(days=7)
        for index in range(max((len(queries) for _, queries in historical), default=0)):
            for provider, queries in historical:
                if index < len(queries):
                    result.append(
                        CollectionPartition(
                            provider.source_id,
                            queries[index],
                            lower,
                            upper,
                            generation=generation,
                            priority=search_acquisition_priority(),
                        )
                    )
        start += span
    for provider in providers:
        result.extend(
            plan_index_collection(
                interval, provider, observed_at=observed_at, version=PLAN_VERSION
            )
        )
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
                    priority=search_acquisition_priority(),
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
    queries: tuple[str, ...] = (query,)
    if not lead.search_title and lead.title.casefold() != "article title unavailable":
        # A dateline or a broad place extracted from the summary can lose the
        # actual reporting headline. Keep that context route as well: headline
        # search can itself miss a useful alternative. Neither route is evidence.
        headline = " ".join(re.findall(r"[\w'-]+", lead.title)[:32])
        queries = tuple(dict.fromkeys(q for q in (headline, query) if q))
    if lead.search_title:
        subject = re.match(
            r"^([\wÀ-ž’'-]+(?:\s+[\wÀ-ž’'-]+){0,4})\s+"
            r"(?:marks?|recalls?|remembers?)\b",
            lead.search_title,
            re.I,
        )
        hazards = disasters_in_text(lead.search_title)
        if subject and len(hazards) == 1:
            # The grammatical subject is a raw search hint, not event geography.
            context = hazards[0].value.replace("_", " ") + ' "' + subject[1] + '"'
            queries = tuple(dict.fromkeys((*queries, context)))
    alternatives = tuple(p for p in providers if p.supports_alternates)
    historical = bool(
        lead.indexed_at and observed_at - lead.indexed_at >= timedelta(days=1)
    )
    provider = next(
        (p for p in alternatives if p.supports_time_filter == historical),
        next(iter(alternatives), None),
    )
    if provider is None:
        return ()
    date_hint = lead.indexed_at or observed_at
    generation = f"{PLAN_VERSION}:{int(observed_at.timestamp()) // 21600}"
    return tuple(
        CollectionPartition(
            provider.source_id,
            alternate_query,
            date_hint - timedelta(days=3),
            date_hint + timedelta(days=1),
            generation=generation,
            alternate_for=lead.canonical_url,
            priority=search_acquisition_priority(alternate_for=lead.canonical_url),
        )
        for alternate_query in queries
    )
