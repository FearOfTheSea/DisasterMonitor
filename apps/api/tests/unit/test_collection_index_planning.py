"""Closed index bins share backfill; recent observations and fetches remain fresh."""

from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.incidents.collection_planning import plan_collection
from disaster_monitor.domain.discovery import ReportingInterval

NOW = datetime(2026, 10, 25, 7, tzinfo=UTC)


class Archive:
    source_id = "immutable-index"
    queries = ("native", "translated")
    supports_time_filter = True
    supports_alternates = False
    index_availability_delay = timedelta(minutes=15)


@pytest.mark.parametrize("days", [1, 3, 7, 14, 30])
def test_closed_bins_reuse_search_identity_across_viewer_generations(days):
    first_interval = ReportingInterval.at_start(days, NOW)
    later = NOW + timedelta(hours=7)
    second_interval = ReportingInterval.at_start(days, later)
    first = plan_collection(first_interval, (Archive(),), observed_at=NOW)
    second = plan_collection(second_interval, (Archive(),), observed_at=later)
    target = NOW.replace(hour=0)
    a = next(p for p in first if p.start == target and p.query == "native")
    b = next(p for p in second if p.start == target and p.query == "native")
    assert a.key == b.key
    assert a.generation == b.generation
    assert a.retrieval_generation != b.retrieval_generation
    assert a.start == b.start and a.end == b.end
    assert all(p.end - p.start == timedelta(hours=6) for p in first)
    assert first_interval.end == NOW and second_interval.end == later


def test_recent_tail_refreshes_without_regenerating_closed_backfill():
    interval = ReportingInterval.at_start(1, NOW)
    initial = plan_collection(interval, (Archive(),), observed_at=NOW)
    same_quarter = plan_collection(
        interval, (Archive(),), observed_at=NOW + timedelta(minutes=10)
    )
    next_quarter = plan_collection(
        interval, (Archive(),), observed_at=NOW + timedelta(minutes=15)
    )
    assert {p.key for p in initial} == {p.key for p in same_quarter}
    tail = next(p for p in initial if p.end > NOW and p.query == "native")
    refreshed = next(
        p for p in next_quarter if p.start == tail.start and p.query == tail.query
    )
    assert refreshed.key != tail.key
    assert refreshed.retrieval_generation == tail.retrieval_generation
    assert {p.key for p in initial if p.end <= NOW} <= {p.key for p in next_quarter}


def test_late_index_windows_do_not_change_the_viewers_publication_interval():
    interval = ReportingInterval.at_start(1, NOW)
    later = NOW + timedelta(hours=14)
    partitions = plan_collection(interval, (Archive(),), observed_at=later)
    assert max(p.start for p in partitions) > interval.end
    assert interval.end == NOW
    assert min(p.start for p in partitions) <= interval.start


def test_live_time_filtered_feed_keeps_its_refresh_generation():
    class Live:
        source_id = "live-index"
        queries = ("flood",)
        supports_time_filter = True
        supports_alternates = False

    interval = ReportingInterval.at_start(1, NOW)
    first = plan_collection(interval, (Live(),), observed_at=NOW)
    second = plan_collection(interval, (Live(),), observed_at=NOW + timedelta(hours=7))
    assert {p.key for p in first}.isdisjoint(p.key for p in second)
    assert all(p.retrieval_generation is None for p in first)
