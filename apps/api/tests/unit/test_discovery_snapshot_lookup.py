"""Inspection must use the retained scan selected by the user."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from disaster_monitor.application.incidents.active_incidents import (
    ActiveIncidentsService,
)
from disaster_monitor.application.incidents.discovery_projection import (
    discovery_incident,
)
from disaster_monitor.application.sources.provider_registry import ProviderRegistry
from disaster_monitor.domain.disaster_types import EventTimePrecision
from disaster_monitor.domain.discovery import (
    DiscoveryArticle,
    DiscoveryRun,
    ReportingInterval,
    assess_article,
    group_reports,
)
from disaster_monitor.domain.event_mentions import MentionTime
from disaster_monitor.domain.evidence_types import SourceReference
from disaster_monitor.infrastructure.geography.static_country_catalog import (
    StaticCountryCatalog,
)
from disaster_monitor.infrastructure.operations.file_discovery_store import (
    FileDiscoveryStore,
)


@pytest.fixture
def runs():
    now = datetime(2026, 10, 20, tzinfo=UTC)
    article = DiscoveryArticle(
        SourceReference(
            "news", "Daily", "Flood", "https://news.example/flood", now, None, now
        ),
        "Floods hit Riverton on 14 October. Two people died.",
    )
    interval = ReportingInterval.at_start(30, now)
    reports = (assess_article(article, interval),)
    event = group_reports(reports)[0]
    original = DiscoveryRun(
        "11111111-1111-4111-8111-111111111111",
        interval,
        "completed",
        reports,
        (event,),
        finished_at=now,
    )
    # Older extraction identifiers used paragraph ordinals. A later parser can
    # assign that same local identifier to a different occurrence.
    newer = replace(
        original,
        scan_id="22222222-2222-4222-8222-222222222222",
        events=(
            replace(
                event,
                location="Other District",
                event_time=event.event_time + timedelta(days=5),
            ),
        ),
        finished_at=now + timedelta(minutes=1),
    )
    return original, newer


async def test_scan_projection_and_lookup_keep_colliding_local_records_separate(
    tmp_path, runs
):
    original, newer = runs
    store = FileDiscoveryStore(tmp_path)
    await store.save(original)
    await store.save(newer)
    service = ActiveIncidentsService(
        ProviderRegistry(()),
        country_catalog=StaticCountryCatalog(),
        discovery_store=store,
    )
    old_reference = discovery_incident(
        original.events[0], original.finished_at, scan_id=original.scan_id
    ).event_id
    new_reference = discovery_incident(
        newer.events[0], newer.finished_at, scan_id=newer.scan_id
    ).event_id
    assert old_reference != new_reference
    old = await service.lookup(old_reference)
    new = await service.lookup(new_reference)
    assert old.location == "Riverton"
    assert old.event_time.day == 14
    assert new.location == "Other District"
    assert new.event_time.day == 19
    assert old.discovery_event == original.events[0]
    assert new.discovery_event == newer.events[0]
    assert await store.read(original.scan_id) == original


async def test_legacy_identifier_without_scan_rejects_colliding_records(tmp_path, runs):
    store = FileDiscoveryStore(tmp_path)
    for run in runs:
        await store.save(run)
    service = ActiveIncidentsService(
        ProviderRegistry(()),
        country_catalog=StaticCountryCatalog(),
        discovery_store=store,
    )
    with pytest.raises(ValueError, match="ambiguous"):
        await service.lookup(runs[0].events[0].event_id)


async def test_scoped_lookup_does_not_fall_back_to_a_different_scan(tmp_path, runs):
    original, newer = runs
    reference = discovery_incident(
        original.events[0], original.finished_at, scan_id=original.scan_id
    ).event_id
    store = FileDiscoveryStore(tmp_path)
    await store.save(newer)
    service = ActiveIncidentsService(
        ProviderRegistry(()),
        country_catalog=StaticCountryCatalog(),
        discovery_store=store,
    )
    with pytest.raises(LookupError):
        await service.lookup(reference)


@pytest.mark.parametrize("fallback", ["publication", "retrieval"])
def test_unknown_mention_time_keeps_fallback_clock_exact(runs, fallback):
    original, _ = runs
    event = original.events[0]
    report = event.reports[0]
    clock = datetime(2026, 10, 20, 23, 9, 50, tzinfo=UTC)
    source = replace(
        report.article.source, published_at=clock if fallback == "publication" else None
    )
    report = replace(
        report,
        article=replace(report.article, source=source),
        mention=replace(report.mention, time=MentionTime("early October")),
    )
    event = replace(event, event_time=None, reports=(report,))

    incident = discovery_incident(event, clock, scan_id=original.scan_id)

    assert incident.event_time == clock
    assert incident.event_time_precision is EventTimePrecision.EXACT
    assert incident.discovery_event.event_time is None


@pytest.mark.parametrize("precision", ["exact", "day", "range"])
def test_projection_precision_belongs_to_selected_onset(runs, precision):
    original, _ = runs
    event = original.events[0]
    report = event.reports[0]
    onset = datetime(2026, 10, 14, 15 if precision == "exact" else 0, tzinfo=UTC)
    selected = replace(
        report,
        mention=replace(
            report.mention,
            time=MentionTime(
                "supported onset", onset, onset + timedelta(days=1), precision
            ),
        ),
    )
    unknown = replace(
        report, mention=replace(report.mention, time=MentionTime("unknown"))
    )
    other = replace(
        report,
        mention=replace(
            report.mention,
            time=MentionTime(
                "another day",
                onset.replace(hour=0) + timedelta(days=1),
                precision="day",
            ),
        ),
    )
    event = replace(event, event_time=onset, reports=(unknown, selected, other))

    incident = discovery_incident(event, original.finished_at, scan_id=original.scan_id)

    assert incident.event_time == onset
    assert incident.event_time_precision.value == precision
    assert incident.event_time_end == (
        selected.mention.time.end if precision == "range" else None
    )
