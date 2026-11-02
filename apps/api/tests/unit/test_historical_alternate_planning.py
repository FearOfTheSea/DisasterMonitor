"""Dated alternatives use historical search without changing publisher facts."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.incidents.collection_planning import (
    plan_alternate_reports,
)
from disaster_monitor.domain.collection import ClaimedCollectionWork
from disaster_monitor.domain.news import NewsFeedItem

NOW = datetime(2026, 11, 2, tzinfo=UTC)


@dataclass
class Provider:
    source_id: str
    supports_time_filter: bool
    supports_alternates: bool = True


RECENT = Provider("recent", False)
HISTORICAL = Provider("dated", True)


def work(indexed_at):
    return ClaimedCollectionWork(
        "work",
        "token",
        "retrieve",
        "publisher",
        None,
        NewsFeedItem(
            "citation",
            "Daily",
            "Article title unavailable",
            "https://daily.example/story",
            None,
            None,
            indexed_at,
            search_title="Lakeview marks 12 years after devastating earthquake - Daily",
        ),
        1,
    )


@pytest.mark.parametrize("providers", [(HISTORICAL, RECENT), (RECENT, HISTORICAL)])
def test_old_index_hint_routes_to_a_time_filter_capable_alternative(providers):
    task = work(NOW - timedelta(days=17))
    parts = plan_alternate_reports(task, providers, observed_at=NOW)
    assert len(parts) == 2
    assert all(p.provider == "dated" and p.priority == 0 for p in parts)
    assert (
        parts[0].query == "Lakeview marks 12 years after devastating earthquake - Daily"
    )
    assert parts[1].query == 'earthquake "Lakeview"'
    assert all(p.alternate_for == task.lead.canonical_url for p in parts)
    assert all(p.start == task.lead.indexed_at - timedelta(days=3) for p in parts)
    assert task.lead.published_at is None and task.lead.updated_at is None
    assert task.lead.search_title.endswith(" - Daily")


@pytest.mark.parametrize("age", [None, timedelta(hours=23), timedelta(hours=-2)])
def test_recent_or_unknown_index_hint_keeps_recent_fallback(age):
    task = work(None if age is None else NOW - age)
    parts = plan_alternate_reports(task, (HISTORICAL, RECENT), observed_at=NOW)
    assert parts and all(p.provider == "recent" for p in parts)


def test_exactly_one_day_old_uses_historical_contract():
    parts = plan_alternate_reports(
        work(NOW - timedelta(days=1)), (RECENT, HISTORICAL), observed_at=NOW
    )
    assert all(p.provider == "dated" for p in parts)


def test_available_fallback_and_one_level_lineage_survive():
    task = work(NOW - timedelta(days=17))
    parts = plan_alternate_reports(task, (RECENT,), observed_at=NOW)
    assert parts and all(p.provider == "recent" for p in parts)
    assert not plan_alternate_reports(
        replace(task, alternate_depth=1), (RECENT, HISTORICAL), observed_at=NOW
    )


@pytest.mark.parametrize("verb", ["recalls", "remembers"])
def test_retrospective_subject_is_a_raw_search_hint_not_an_asserted_place(verb):
    task = work(NOW - timedelta(days=4))
    task = replace(
        task,
        lead=replace(
            task.lead, search_title=f"The local council {verb} the flood victims"
        ),
    )
    parts = plan_alternate_reports(task, (HISTORICAL,), observed_at=NOW)
    assert parts[1].query == 'flood "The local council"'
    assert len(parts) == 2
