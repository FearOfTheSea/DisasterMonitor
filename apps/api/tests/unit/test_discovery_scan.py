import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.domain.disaster_types import Disaster
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryBatch,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.evidence_types import SourceReference

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "headline, expected",
    [
        ("Drought in Riverton", ("Three people died.",)),
        ("Humanitarian situation report", ()),
    ],
)
def test_disaster_accounts_do_not_promote_other_hazards_conflict_or_disease(
    headline, expected
):
    report = replace(
        article(headline),
        text=(
            "Drought disrupted the water supply. Three people died. "
            "Violence killed 40 people. Cholera caused 17 deaths. "
            "Floods killed five people."
        ),
    )
    # The headline-independent case has both flood and drought and cannot admit
    # one unambiguous event, but neither branch may attribute those unrelated deaths.
    assessed = assess_article(report, ReportingInterval.at_start(7, NOW))
    assert assessed.fatality_evidence == expected


def article(title="Flood in Riverton", **kwargs):
    source = SourceReference(
        source_id="open-news",
        publisher="Unfamiliar News",
        title=title,
        canonical_url="https://unfamiliar.example/report",
        published_at=NOW,
        updated_at=None,
        retrieved_at=NOW,
    )
    return DiscoveryArticle(
        source=source, text="Officials said two people died in the flood.", **kwargs
    )


@pytest.mark.parametrize("days", [1, 3, 7, 14, 30])
def test_publication_interval_is_fixed_and_inclusive(days):
    interval = ReportingInterval.at_start(days, NOW)
    assert interval.start == NOW - timedelta(days=days)
    report = article(event_time=NOW - timedelta(days=100), indexed_at=NOW)
    for date in (interval.start, NOW):
        assert (
            assess_article(
                replace(report, source=replace(report.source, published_at=date)),
                interval,
            ).eligibility
            == "eligible"
        )
    for date in (
        interval.start - timedelta(microseconds=1),
        NOW + timedelta(microseconds=1),
        None,
    ):
        assert (
            assess_article(
                replace(report, source=replace(report.source, published_at=date)),
                interval,
            ).eligibility
            != "eligible"
        )


@pytest.mark.parametrize(
    "hazard,title",
    [
        (Disaster.EARTHQUAKE, "Earthquake in Riverton"),
        (Disaster.FLOOD, "Flood in Riverton"),
        (Disaster.WILDFIRE, "Wildfire in Riverton"),
        (Disaster.LANDSLIDE, "Landslide in Riverton"),
        (Disaster.DROUGHT, "Drought in Riverton"),
        (Disaster.TROPICAL_CYCLONE, "Typhoon in Riverton"),
        (Disaster.VOLCANIC_ERUPTION, "Volcanic eruption in Riverton"),
    ],
)
def test_open_discovery_all_categories_and_attributed_body_fatalities(hazard, title):
    # Every category needs its own source context; a flood sentence cannot serve
    # as death evidence for an earthquake, wildfire, or another hazard.
    sentence = (
        f"Officials said two people died in the {hazard.value.replace('_', ' ')}."
    )
    assessed = assess_article(
        replace(article(title), text=sentence), ReportingInterval.at_start(7, NOW)
    )
    assert assessed.disaster == hazard
    assert assessed.fatality_evidence == (sentence,)
    assert assessed.article.source.publisher == "Unfamiliar News"


def test_major_is_not_a_fatality_claim_and_unknown_dates_are_retained():
    report = article("Major flood in Riverton")
    assessed = assess_article(
        replace(report, text="Evacuations continue. No deaths were reported."),
        ReportingInterval.at_start(7, NOW),
    )
    assert assessed.eligibility == "eligible"
    assert assessed.fatality_evidence == ()
    unknown = assess_article(
        replace(report, source=replace(report.source, published_at=None)),
        ReportingInterval.at_start(7, NOW),
    )
    assert unknown.eligibility == "unknown_publication"


def test_duplicates_syndication_and_separate_nearby_events():
    first = article(event_key="event-a", origin="wire:123", location="Riverton")
    copy = replace(
        first, source=replace(first.source, canonical_url="https://copy.example/a")
    )
    separate = replace(
        first,
        event_key="event-b",
        source=replace(first.source, canonical_url="https://other.example/b"),
    )
    interval = ReportingInterval.at_start(7, NOW)
    groups = group_reports(
        tuple(assess_article(item, interval) for item in (first, first, copy, separate))
    )
    assert len(groups) == 2
    assert len(groups[0].reports) == 2
    assert groups[0].independent_origins == 1
    assert groups[0].geometry is None


def test_unknown_dates_attach_only_to_an_already_eligible_explicit_event():
    first = article(event_key="event-a")
    unknown = replace(
        first,
        source=replace(
            first.source, published_at=None, canonical_url="https://unknown.example/a"
        ),
    )
    unrelated = replace(unknown, event_key="other")
    interval = ReportingInterval.at_start(7, NOW)
    groups = group_reports(
        tuple(assess_article(a, interval) for a in (unknown, first, unrelated))
    )
    assert len(groups) == 1
    assert len(groups[0].reports) == 2
    assert any(r.article.source.published_at is None for r in groups[0].reports)


async def test_terminal_storage_failure_is_explicit_instead_of_running_forever(
    tmp_path,
):
    from disaster_monitor.application.incidents.discovery_scan import (
        DiscoveryScanService,
    )
    from disaster_monitor.infrastructure.operations.file_discovery_store import (
        FileDiscoveryStore,
    )

    class Store(FileDiscoveryStore):
        async def save(self, run):
            if run.status != "running":
                raise OSError("controlled disk failure")
            await super().save(run)

    class Feed:
        source_id = "fixture"

        async def discover(self, *, interval):
            yield DiscoveryBatch(articles=(article(),), successful_operations=1)

    service = DiscoveryScanService((Feed(),), Store(tmp_path), clock=lambda: NOW)
    run = await service.start(7)
    await service.wait(run.scan_id)
    result = await service.get(run.scan_id)
    assert result.status == "incomplete"
    assert result.events
    assert any("persistence" in issue for issue in result.issues)
    await service.aclose()


@pytest.mark.asyncio
async def test_scan_sharing_partial_failure_empty_failure_and_truncation(tmp_path):
    from disaster_monitor.application.incidents.discovery_scan import (
        DiscoveryScanService,
    )
    from disaster_monitor.infrastructure.operations.file_discovery_store import (
        FileDiscoveryStore,
    )

    gate = asyncio.Event()

    class Feed:
        source_id = "fixture"
        calls = 0

        async def discover(self, *, interval):
            self.calls += 1
            await gate.wait()
            yield DiscoveryBatch(articles=(article(),), successful_operations=1)
            yield DiscoveryBatch(
                issues=("fixture partition failed",),
                failed_operations=1,
                truncated=True,
            )

    feed = Feed()
    service = DiscoveryScanService(
        (feed,), FileDiscoveryStore(tmp_path), clock=lambda: NOW
    )
    one, two = await asyncio.gather(service.start(7), service.start(7))
    assert one.scan_id == two.scan_id
    assert one.status == "running"
    gate.set()
    await service.wait(one.scan_id)
    result = await service.get(one.scan_id)
    assert feed.calls == 1
    assert result.status == "incomplete"
    assert len(result.events) == 1
    assert result.events[0].geometry is None
    assert result.issues
    assert (await FileDiscoveryStore(tmp_path).read(one.scan_id)) == result
    await service.aclose()

    for batch, expected in (
        (DiscoveryBatch(successful_operations=1), "completed"),
        (DiscoveryBatch(failed_operations=1, issues=("failed",)), "failed"),
    ):

        class ResultFeed:
            source_id = "result"

            def __init__(self, result):
                self.result = result

            async def discover(self, *, interval):
                yield self.result

        service = DiscoveryScanService(
            (ResultFeed(batch),), FileDiscoveryStore(tmp_path), clock=lambda: NOW
        )
        run = await service.start(1)
        await service.wait(run.scan_id)
        result = await service.get(run.scan_id)
        assert result.status == expected
        assert result.events == ()
        await service.aclose()


async def test_timeout_retains_results_and_restart_marks_interruption(
    tmp_path,
):
    from disaster_monitor.application.incidents.discovery_scan import (
        DiscoveryScanService,
    )
    from disaster_monitor.infrastructure.operations.file_discovery_store import (
        FileDiscoveryStore,
    )

    class SlowFeed:
        source_id = "slow"

        async def discover(self, *, interval):
            yield DiscoveryBatch(articles=(article(),), successful_operations=1)
            await asyncio.Event().wait()

    store = FileDiscoveryStore(tmp_path)
    service = DiscoveryScanService(
        (SlowFeed(),), store, clock=lambda: NOW, provider_timeout_seconds=0.05
    )
    run = await service.start(7)
    await service.wait(run.scan_id)
    result = await service.get(run.scan_id)
    assert result.status == "incomplete"
    assert len(result.events) == 1
    assert result.failed_operations == 1
    interrupted = replace(result, status="running")
    await store.save(interrupted)
    await FileDiscoveryStore(tmp_path).recover()
    assert (await store.read(run.scan_id)).status == "incomplete"
    await service.aclose()


@pytest.mark.parametrize(
    "headline",
    [
        "Venezuela Earthquakes Situation Report",
        "Floods damage roads in Riverton",
        "Wildfires force evacuations",
        "Landslides block bridges",
        "Droughts threaten rural water supplies",
        "Tropical storms damage electricity networks",
        "Volcanic eruptions disrupt communications",
    ],
)
def test_plural_hazard_reporting_is_not_lost_at_classification(headline):
    assessed = assess_article(
        replace(article(headline), text=""), ReportingInterval.at_start(7, NOW)
    )
    assert assessed.eligibility == "eligible"
    assert assessed.disaster is not None


def test_recent_retrospective_article_qualifies_without_claiming_recent_onset():
    report = article(
        "Flood anniversary in Riverton", event_time=NOW - timedelta(days=365)
    )
    assessed = assess_article(
        replace(report, text="Two people died one year ago."),
        ReportingInterval.at_start(7, NOW),
    )
    assert assessed.eligibility == "eligible"
    assert assessed.fatality_evidence == ()
    assert group_reports((assessed,))[0].event_time == NOW - timedelta(days=365)


async def test_ten_compatible_requests_share_one_scan_and_different_periods_do_not(
    tmp_path,
):
    from disaster_monitor.application.incidents.discovery_scan import (
        DiscoveryScanService,
    )
    from disaster_monitor.infrastructure.operations.file_discovery_store import (
        FileDiscoveryStore,
    )

    gate = asyncio.Event()

    class Feed:
        source_id = "fixture"

        async def discover(self, *, interval):
            await gate.wait()
            yield DiscoveryBatch(successful_operations=1)

    service = DiscoveryScanService(
        (Feed(),), FileDiscoveryStore(tmp_path), clock=lambda: NOW
    )
    runs = await asyncio.gather(*(service.start(7) for _ in range(10)))
    assert len({run.scan_id for run in runs}) == 1
    other = await service.start(14)
    assert other.scan_id != runs[0].scan_id
    gate.set()
    await asyncio.gather(service.wait(other.scan_id), service.wait(runs[0].scan_id))
    await service.aclose()


def test_same_headline_and_country_without_event_identity_remain_separate():
    first = article(location="Japan")
    second = replace(
        first, source=replace(first.source, canonical_url="https://other.example/story")
    )
    interval = ReportingInterval.at_start(7, NOW)
    assert (
        len(
            group_reports(
                tuple(assess_article(item, interval) for item in (first, second))
            )
        )
        == 2
    )


def test_precise_shared_point_and_onset_associate_different_headlines():
    from disaster_monitor.domain.events import (
        EventCoordinate,
        EventGeometry,
        EventGeometryKind,
    )

    first = article(event_time=NOW, location="Riverton")
    first = replace(
        first,
        geometry=EventGeometry(
            EventGeometryKind.POINT,
            first.source,
            coordinates=(EventCoordinate(12, 105),),
        ),
    )
    second = replace(
        first,
        source=replace(
            first.source,
            title="Flood aftermath in Riverton",
            canonical_url="https://other.example/story",
        ),
    )
    separate = replace(
        second,
        event_time=NOW + timedelta(hours=1),
        source=replace(second.source, canonical_url="https://third.example/story"),
    )
    interval = ReportingInterval.at_start(7, NOW)
    groups = group_reports(
        tuple(assess_article(item, interval) for item in (first, second, separate))
    )
    assert len(groups) == 2
    assert len(groups[0].reports) == 2


def test_nearby_events_and_country_only_metadata_do_not_merge():
    report = article(location="Riverton", event_time=NOW)
    other = replace(
        report,
        location="East Riverton",
        source=replace(report.source, canonical_url="https://other.example/story"),
    )
    interval = ReportingInterval.at_start(7, NOW)
    assert (
        len(
            group_reports(
                tuple(assess_article(item, interval) for item in (report, other))
            )
        )
        == 2
    )
