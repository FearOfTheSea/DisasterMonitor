"""Editorial titles guide bounded search without becoming publisher facts."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from disaster_monitor.application.incidents.collection_planning import (
    plan_alternate_reports,
)
from disaster_monitor.domain.collection import ClaimedCollectionWork
from disaster_monitor.domain.news import NewsFeedItem
from disaster_monitor.infrastructure.news.bing_collection import (
    BingRssCollectionProvider,
)

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def test_native_citation_title_precedes_english_index_geography_in_alternate_search():
    lead = NewsFeedItem(
        "citation",
        "Index",
        "Article title unavailable",
        "https://daily.example/report",
        None,
        None,
        discovery_hint="Earthquake killed one person in Highland County.",
        search_title='"Un residente falleció durante el terremoto"',
    )
    work = ClaimedCollectionWork(
        "work", "token", "retrieve", "publisher", None, lead, 1
    )
    (part,) = plan_alternate_reports(
        work, (BingRssCollectionProvider(),), observed_at=NOW
    )
    assert part.query == "Un residente falleció durante el terremoto"
    assert part.alternate_for == lead.canonical_url
    assert part.priority == 1
    assert not plan_alternate_reports(
        replace(work, alternate_depth=1),
        (BingRssCollectionProvider(),),
        observed_at=NOW,
    )


@pytest.mark.parametrize("title", ["", " " * 4, "a" * 301])
def test_search_headline_has_a_bounded_nonempty_contract(title):
    with pytest.raises(ValueError, match="search title"):
        NewsFeedItem(
            "citation",
            "Index",
            "Unknown",
            "https://daily.example/report",
            None,
            None,
            search_title=title,
        )
