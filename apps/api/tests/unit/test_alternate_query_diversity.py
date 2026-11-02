"""Fallback searches retain distinct headline and contextual routes."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime

from disaster_monitor.application.incidents.collection_planning import (
    plan_alternate_reports,
)
from disaster_monitor.domain.collection import ClaimedCollectionWork
from disaster_monitor.domain.news import NewsFeedItem

NOW = datetime(2026, 11, 1, tzinfo=UTC)


@dataclass
class SearchProvider:
    source_id: str = "index"
    supports_alternates: bool = True
    supports_time_filter: bool = False


def work(title, hint=None, search_title=None):
    return ClaimedCollectionWork(
        "work",
        "token",
        "retrieve",
        "publisher",
        None,
        NewsFeedItem(
            "lead",
            "Daily",
            title,
            "https://daily.example/report",
            None,
            None,
            NOW,
            discovery_hint=hint,
            search_title=search_title,
        ),
        1,
    )


def test_dateline_does_not_erase_the_available_headline_or_old_context_route():
    task = work(
        "Families hold a vigil for Eastbrook flood victims",
        "District headquarters, Monday -- Local organisers have announced plans "
        "for a vigil after the recent flooding.",
    )
    parts = plan_alternate_reports(task, (SearchProvider(),), observed_at=NOW)
    assert parts[0].query == task.lead.title
    assert len(parts) == 2
    assert parts[1].query.startswith("District headquarters Monday -- Local")
    assert all(
        p.alternate_for == task.lead.canonical_url and p.priority == 0 for p in parts
    )
    assert task.lead.title == "Families hold a vigil for Eastbrook flood victims"


def test_context_route_survives_when_headline_route_loses_place_or_reporting_context():
    task = work("District weekly roundup", "Floods struck Lakeview. Two people died.")
    parts = plan_alternate_reports(task, (SearchProvider(),), observed_at=NOW)
    assert parts[0].query == "District weekly roundup"
    assert any("Lakeview" in p.query and "flood" in p.query.lower() for p in parts[1:])


def test_same_query_is_not_enqueued_twice():
    task = work("Flood anniversary observance")
    parts = plan_alternate_reports(task, (SearchProvider(),), observed_at=NOW)
    assert len(parts) == 1
    assert parts[0].query == task.lead.title


def test_native_headline_remains_the_single_preferred_route():
    task = work(
        "Article title unavailable",
        "Floods struck Lakeview.",
        "Dos muertos tras las inundaciones",
    )
    parts = plan_alternate_reports(task, (SearchProvider(),), observed_at=NOW)
    assert len(parts) == 1
    assert parts[0].query == "Dos muertos tras las inundaciones"


def test_unavailable_title_uses_context_without_searching_the_placeholder():
    parts = plan_alternate_reports(
        work("Article title unavailable", "Floods struck Lakeview."),
        (SearchProvider(),),
        observed_at=NOW,
    )
    assert len(parts) == 1 and "Lakeview" in parts[0].query
    assert "unavailable" not in parts[0].query


def test_routes_have_word_bounds_and_do_not_expand_recursively_or_across_providers():
    task = work(" ".join(f"word{i}" for i in range(40)), "Floods struck Lakeview.")
    providers = (SearchProvider(), SearchProvider("second"))
    parts = plan_alternate_reports(task, providers, observed_at=NOW)
    assert len(parts) == 2 and all(p.provider == "index" for p in parts)
    assert len(parts[0].query.split()) == 32
    assert not plan_alternate_reports(
        replace(task, alternate_depth=1), providers, observed_at=NOW
    )
